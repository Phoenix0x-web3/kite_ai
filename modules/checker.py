import asyncio
import json
import random
import secrets
import time

from web3.types import TxParams

from libs.base import Base
from libs.eth_async.client import Client
from libs.eth_async.data.models import Networks, TokenAmount, RawContract
from modules.chain_api import BlockScout
from utils.browser import Browser
from utils.db_api.models import Wallet
from utils.logs_decorator import controller_log
from utils.retry import async_retry

KITE_AIRDROP_CONTRACT = "0xb4Aa12EfbF88eAB4Bf7E4625A1CEb21cb81290bB"
KITE_AIRDROP_ABI = [
    {"inputs": [{"internalType": "uint256", "name": "amount", "type": "uint256"},
                {"internalType": "bytes32[]", "name": "merkleProof", "type": "bytes32[]"}], "name": "claimAirdrop",
     "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"internalType": "address", "name": "", "type": "address"}], "name": "hasClaimed",
     "outputs": [{"internalType": "bool", "name": "", "type": "bool"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"internalType": "address", "name": "wallet", "type": "address"},
                {"internalType": "uint256", "name": "amount", "type": "uint256"},
                {"internalType": "bytes32[]", "name": "merkleProof", "type": "bytes32[]"}], "name": "checkEligibility",
     "outputs": [{"internalType": "bool", "name": "isEligible", "type": "bool"},
                 {"internalType": "bool", "name": "canClaim", "type": "bool"}], "stateMutability": "view",
     "type": "function"},
    {"inputs": [], "name": "token", "outputs": [{"internalType": "address", "name": "", "type": "address"}],
     "stateMutability": "view", "type": "function"}
]

class KiteAIChecker(Base):
    __module_name__ = "Kite AI Checker"

    CHECKER_API = "https://airdrop-backend.prod.gokite.ai"

    def __init__(self, client: Client, wallet: Wallet):
        self.client = client
        self.wallet = wallet
        self.session = Browser(wallet=wallet)
        self.onchain_api = BlockScout(client=client, wallet=wallet)
        self.base_headers = {
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://claim.kite.foundation",
            "Referer": "https://claim.kite.foundation",
        }
        self.auth_token = None
        self.eoa_address = self.wallet.eoa_address
        self.paused = False

    @async_retry(retries=3, delay=3)
    async def sign_in(self, registration=False) -> dict:
        url = f"{self.CHECKER_API}/api/v1/auth/authenticate"

        body = {"wallet_address": self.client.account.address.lower()}

        ts = str(int(time.time()))
        nonce = secrets.token_hex(32)

        body_json_compact = json.dumps(body, ensure_ascii=False, separators=(",", ":"))

        message_lines = [
            self.client.account.address.lower(),
            "POST",
            "/api/v1/auth/authenticate",
            body_json_compact,
            ts,
            nonce,
        ]

        message = "\n".join(message_lines)

        sig = await self.sign_message(text=message)

        headers = {
            **self.base_headers,
            "content-type": "text/plain;charset=UTF-8",
            "priority": "u=1, i",
            "x-auth-timestamp": ts,
            "x-auth-nonce": nonce,
            "x-auth-signature": sig,
        }

        data = {"wallet_address": self.client.account.address.lower()}

        r = await self.session.post(url=url, headers=headers, json=data, timeout=60)
        r.raise_for_status()

        self.auth_token = r.json().get("data").get("jwt")

        return r.json()

    async def get_token_allocation(self):
        headers = {**self.base_headers, "Content-Type": "application/json", "Authorization": f"Bearer {self.auth_token}"}

        r = await self.session.get(
            url=f"{self.CHECKER_API}/api/v1/allocations/eligibility/{self.client.account.address.lower()}", headers=headers
        )

        return r.json().get("data")  # .get('token_amount')

    @controller_log("Airdrop Checker")
    async def check_kite_ai(self):
        await self.sign_in()

        alloca = await self.get_token_allocation()

        if alloca.get("is_eligible"):
            self.wallet.eligible = alloca.get("is_eligible")
            self.wallet.airdrop = int(alloca.get("token_amount"))

            return f"Token Allocation {alloca}"

        return f"Not Eligble | {alloca}"

    async def get_merkle_proof(self) -> list[str]:
        await self.sign_in()
        url = f"{self.CHECKER_API}/api/v1/merkle/proof"
        headers = {**self.base_headers, "Content-Type": "application/json",
                   "Authorization": f"Bearer {self.auth_token}"}

        payload = {"wallet_address": self.client.account.address.lower()}
        r = await self.session.post(url=url, headers=headers, json=payload, timeout=30)
        data = r.json().get("data") or {}
        return data.get("merkle_proof") or data.get("proof") or []

    @controller_log("Airdrop Claim")
    async def claim_controller(self) -> str:

        eth_client = Client(private_key=self.wallet.private_key, proxy=self.wallet.proxy, network=Networks.Ethereum)

        proof = await self.get_merkle_proof()

        AIRDROP_CONTRACT = RawContract(
            title='airdrop',
            address='0xdf9aCedDd8a8C130DFe3015C0b1B507cf6571fc9',
            abi=KITE_AIRDROP_ABI
        )

        c = await self.client.contracts.get(contract_address=AIRDROP_CONTRACT)

        amount = TokenAmount(amount=self.wallet.airdrop, decimals=18)
        data = c.encode_abi("claimAirdrop", [amount.Wei, proof])

        tx_params = TxParams(to=c.address, data=data, value=0)

        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)

        await asyncio.sleep(random.randint(2, 4))

        rcpt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if rcpt:
            return f"Success claimed {self.wallet.airdrop} KITE on Ethereum Mainnet"
