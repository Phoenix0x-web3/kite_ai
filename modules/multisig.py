import asyncio
import json
import random
import time
from typing import Dict

from eth_account.messages import encode_typed_data
from web3 import Web3, constants
from web3.types import TxParams, TxReceipt

from data.settings import Settings
from libs.base import Base
from libs.eth_async.classes import Singleton
from libs.eth_async.client import Client
from libs.eth_async.data.models import RawContract, TokenAmount, TxArgs
from utils.browser import Browser
from utils.db_api.models import Wallet
from utils.logs_decorator import controller_log
from utils.retry import async_retry

SAFE_PROXY_FACTORY_MIN_ABI = [
    {
        "type": "function",
        "name": "createProxyWithNonce",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "_singleton", "type": "address"},
            {"name": "initializer", "type": "bytes"},
            {"name": "saltNonce", "type": "uint256"},
        ],
        "outputs": [{"name": "proxy", "type": "address"}],
    }
]

SAFE_L2_MIN_ABI = [
    {
        "type": "function",
        "name": "setup",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "_owners", "type": "address[]"},
            {"name": "_threshold", "type": "uint256"},
            {"name": "to", "type": "address"},
            {"name": "data", "type": "bytes"},
            {"name": "fallbackHandler", "type": "address"},
            {"name": "paymentToken", "type": "address"},
            {"name": "payment", "type": "uint256"},
            {"name": "paymentReceiver", "type": "address"},
        ],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "nonce",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "execTransaction",
        "stateMutability": "payable",
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
            {"name": "data", "type": "bytes"},
            {"name": "operation", "type": "uint8"},
            {"name": "safeTxGas", "type": "uint256"},
            {"name": "baseGas", "type": "uint256"},
            {"name": "gasPrice", "type": "uint256"},
            {"name": "gasToken", "type": "address"},
            {"name": "refundReceiver", "type": "address"},
            {"name": "signatures", "type": "bytes"}
        ],
        "outputs": [{"name": "success", "type": "bool"}],
    }
]

SAFE_TX_TYPES = {
    "EIP712Domain": [
        {"name": "chainId", "type": "uint256"},
        {"name": "verifyingContract", "type": "address"},
    ],
    "SafeTx": [
        {"name": "to",             "type": "address"},
        {"name": "value",          "type": "uint256"},
        {"name": "data",           "type": "bytes"},
        {"name": "operation",      "type": "uint8"},
        {"name": "safeTxGas",      "type": "uint256"},
        {"name": "baseGas",        "type": "uint256"},
        {"name": "gasPrice",       "type": "uint256"},
        {"name": "gasToken",       "type": "address"},
        {"name": "refundReceiver", "type": "address"},
        {"name": "nonce",          "type": "uint256"},
    ],
}


ADDR0 = Web3.to_checksum_address("0x" + "00" * 20)

SUPERCHAIN_MODULE_MIN_ABI = [
    {
        "type": "function",
        "name": "getUserSuperChainAccount",
        "stateMutability": "view",
        "inputs": [{"name": "user", "type": "address"}],
        "outputs": [{"name": "account", "type": "address"}, {"name": "exists", "type": "bool"}],
    },
]


class SafeAddresses:
    FACTORY_V130 = Web3.to_checksum_address("0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2")
    SAFE_L2_V130 = Web3.to_checksum_address("0x3E5c63644E683549055b9Be8653de26E0B4CD36E")
    CFH_V130 = Web3.to_checksum_address("0xf48f2B2d2a534e402487b3ee7C18c33Aec0Fe5e4")


class SafeContracts(Singleton):
    SAFE_PROXY_FACTORY = RawContract(
        title="SAFE_PROXY_FACTORY_130",
        address=SafeAddresses.FACTORY_V130,
        abi=SAFE_PROXY_FACTORY_MIN_ABI,
    )
    SAFE_L2_V130 = RawContract(
        title="SAFE_L2_V130",
        address=SafeAddresses.SAFE_L2_V130,
        abi=SAFE_L2_MIN_ABI,
    )


class Safe(Base):
    __module_name__ = "Safe Module"

    BASE = "https://wallet-client.ash.center"

    def __init__(self, client: Client, wallet: Wallet, salt_nonce: int = 0):
        self.client = client
        self.wallet = wallet
        self.salt_nonce = int(salt_nonce)
        self.session = Browser(wallet=wallet)

    @async_retry(retries=3, delay=5)
    async def get_safe_addresses(self):
        url = f"{self.BASE}/v1/owners/{self.client.account.address.lower()}/safes"

        r = await self.session.get(url=url)

        if r.json().get("code") == 429:
            return "Failed"

        return r.json().get("2368")

    async def get_safe_nonce(self, address: str):
        url = f"{self.BASE}/v1/chains/2368/safes/{address}/nonces"

        r = await self.session.get(url=url)

        return r.json()

    async def get_safe_info(self, address: str):
        url = f"{self.BASE}/v1/chains/2368/safes/{address}"

        r = await self.session.get(url=url)

        return r.json()

    @controller_log("Deposit to Multisig")
    async def send_native_to_multisig(self, address):

        settings = Settings()

        percent = (
            random.randint(
                settings.multisig_percent_min,
                settings.multisig_percent_max,
            )
            / 100
        )

        balance = await self.client.wallet.balance()

        amount = float(balance.Ether) * percent

        # receiver = random.choice(wallets)
        return await self.send_eth(to_address=Web3.to_checksum_address(address), amount=TokenAmount(amount=amount))

    async def encode_initializer(self) -> bytes:
        safe = await self.client.contracts.get(SafeContracts.SAFE_L2_V130)
        return safe.encodeABI(
            fn_name="setup",
            args=(
                [self.client.account.address],
                1,
                constants.ADDRESS_ZERO,
                b"",
                SafeAddresses.CFH_V130,
                constants.ADDRESS_ZERO,
                0,
                constants.ADDRESS_ZERO,
            ),
        )

    @controller_log("Create Multisig Wallet")
    async def create_account(self) -> TxReceipt:
        factory = await self.client.contracts.get(SafeContracts.SAFE_PROXY_FACTORY)
        initializer = await self.encode_initializer()

        salt = int(time.time())

        data = TxArgs(x=SafeContracts.SAFE_L2_V130.address, c=initializer, s=salt).tuple()

        e = factory.encodeABI("createProxyWithNonce", args=data)

        tx_params = TxParams(to=factory.address, data=e, value=0)

        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)
        await asyncio.sleep(random.randint(2, 4))
        rcpt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if rcpt:
            return f"Success created Multisig Wallet"

        return "Failed | Creating Multisig Wallet"

    def pack_signatures(self, sigs) -> bytes:
        sigs_sorted = sorted(sigs, key=lambda x: x[0].lower())
        return b"".join(s for _, s in sigs_sorted)

    async def find_safe_with_balance(self):
        safes = await self.get_safe_addresses()
        for safe in safes:
            balance = await self.client.wallet.balance(address=safe)
            if balance.Ether > 0:
                return safe, balance

        raise Exception('Safes has no balances')


    def build_safe_typed_data(self, domain, message) -> Dict:
        td = {
            "types": SAFE_TX_TYPES,
            "primaryType": "SafeTx",
            "domain": {
                "chainId": int(domain["chainId"]),
                "verifyingContract": Web3.to_checksum_address(domain["verifyingContract"]),
            },
            "message": {
                "to": Web3.to_checksum_address(message["to"]),
                "value": int(message["value"]),
                "data": Web3.to_bytes(hexstr=message.get("data", "0x")),
                "operation": int(message.get("operation", 0)),
                "safeTxGas": int(message.get("safeTxGas", 0)),
                "baseGas": int(message.get("baseGas", 0)),
                "gasPrice": int(message.get("gasPrice", 0)),
                "gasToken": Web3.to_checksum_address(message.get("gasToken", ADDR0)),
                "refundReceiver": Web3.to_checksum_address(message.get("refundReceiver", ADDR0)),
                "nonce": int(message["nonce"]),
            },
        }
        return td

    async def sign_safe_typed_data(self, typed_data):
        #a = await self.sign_message()
        signed_typed_data = encode_typed_data(full_message=typed_data)
        signed = self.client.account.sign_message(signed_typed_data)
        r = signed.r.to_bytes(32, "big")
        s = signed.s.to_bytes(32, "big")
        v = bytes([signed.v])  # 27/28
        sig_bytes = r + s + v

        return {
            "safe_tx_hash": signed.messageHash.hex(),
            "sig": "0x" + (r + s + v).hex(),
            "sig_bytes": sig_bytes,
            "signer": self.client.account.address,
        }

    controller_log('Send from Multisig')
    async def send_native_from_safe(self):
        safe, balance = await self.find_safe_with_balance()
        # safe = '0x73e62d3Af60fc87FbF3A02D8cf01c63AbE14724f'
        # balance = TokenAmount(amount=0.01)

        contract = RawContract(title='Safe', address=safe, abi=SAFE_L2_MIN_ABI)

        contract = await self.client.contracts.get(contract_address=contract)

        nonce = await contract.functions.nonce().call()

        typed = self.build_safe_typed_data(
            domain={"verifyingContract": contract.address, "chainId": self.client.network.chain_id},
            message={
                "to": self.client.account.address,
                "value": balance.Wei,
                "data": "0x",
                "operation": 0,
                "safeTxGas": 0,
                "baseGas": 0,
                "gasPrice": 0,
                "gasToken": ADDR0,
                "refundReceiver": ADDR0,
                "nonce": nonce,
            },
        )
        sign = await self.sign_safe_typed_data(typed_data=typed)

        data = contract.encodeABI('execTransaction', args=[

                self.client.account.address,
                balance.Wei,
                Web3.to_bytes(hexstr="0x"),
                0,
                0,
                0,
                0,
                ADDR0,
                ADDR0,
                sign['sig_bytes']

        ])

        tx_params = TxParams(to=contract.address, data=data, value=0)

        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)
        await asyncio.sleep(random.randint(2, 4))
        rcpt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if rcpt:
            return f"Success sended {balance} KITE from SAFE to self address"

        return "Failed | Sending {balance} KITE from SAFE to self address"