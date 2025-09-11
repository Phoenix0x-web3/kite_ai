import asyncio
import random

from web3 import Web3, constants
from dataclasses import dataclass

from web3.types import TxReceipt, TxParams

from data.config import ABIS_DIR
from data.settings import Settings
from libs.base import Base
from libs.eth_async.classes import Singleton
from libs.eth_async.client import Client
from libs.eth_async.data.models import RawContract, TxArgs, TokenAmount
from libs.eth_async.utils.files import read_json
from utils.browser import Browser
from utils.db_api.models import Wallet
from web3 import Web3

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
        "type": "function", "name": "setup", "stateMutability": "nonpayable",
        "inputs": [
            {"name": "_owners", "type": "address[]"},
            {"name": "_threshold", "type": "uint256"},
            {"name": "to", "type": "address"},
            {"name": "data", "type": "bytes"},
            {"name": "fallbackHandler", "type": "address"},
            {"name": "paymentToken", "type": "address"},
            {"name": "payment", "type": "uint256"},
            {"name": "paymentReceiver", "type": "address"}
        ],
        "outputs": []
    }
]

ADDR0 = Web3.to_checksum_address("0x" + "00" * 20)

SUPERCHAIN_MODULE_MIN_ABI = [
    {
        "type": "function",
        "name": "getUserSuperChainAccount",
        "stateMutability": "view",
        "inputs": [{"name": "user", "type": "address"}],
        "outputs": [
            {"name": "account", "type": "address"},
            {"name": "exists", "type": "bool"}
        ],
    },
]


class SafeAddresses:
    FACTORY_V130 = Web3.to_checksum_address("0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2")
    SAFE_L2_V130 = Web3.to_checksum_address("0x3E5c63644E683549055b9Be8653de26E0B4CD36E")
    CFH_V130 = Web3.to_checksum_address("0xf48f2B2d2a534e402487b3ee7C18c33Aec0Fe5e4")


class SafeContracts(Singleton):
    SAFE_PROXY_FACTORY = RawContract(
        title='SAFE_PROXY_FACTORY_130',
        address=SafeAddresses.FACTORY_V130,
        abi=SAFE_PROXY_FACTORY_MIN_ABI,
    )
    SAFE_L2_V130 = RawContract(
        title='SAFE_L2_V130',
        address=SafeAddresses.SAFE_L2_V130,
        abi=SAFE_L2_MIN_ABI,
    )


class Safe(Base):
    __module_name__ = "Safe Module"

    BASE = 'https://wallet-client.ash.center'

    def __init__(self, client: Client, wallet: Wallet, salt_nonce: int = 24):
        self.client = client
        self.wallet = wallet
        self.salt_nonce = int(salt_nonce)
        self.session = Browser(wallet=wallet)

    @async_retry(retries=3, delay=3)
    async def get_safe_addresses(self):
        url = f"{self.BASE}/v1/owners/{self.client.account.address.lower()}/safes"

        r = await self.session.get(url=url)

        return r.json().get('2368')

    async def get_safe_nonce(self, address: str):
        url = f"{self.BASE}/v1/chains/2368/safes/{address}/nonces"

        r = await self.session.get(url=url)

        return r.json()

    @controller_log('Deposit to Multisig')
    async def send_native_to_multisig(self):
        wallets = await self.get_safe_addresses()

        if not wallets:
            return await self.create_account()

        settings = Settings()

        percent = random.randint(
            settings.swaps_percent_min,
            settings.swaps_percent_max,
        )

        balance = await self.client.wallet.balance()
        amount = float(balance.Ether) * percent

        receiver = random.choice(wallets)
        return await self.send_eth(to_address=receiver, amount=TokenAmount(amount=amount))

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

    @controller_log('Create Multisig Wallet')
    async def create_account(self) -> TxReceipt:
        factory = await self.client.contracts.get(SafeContracts.SAFE_PROXY_FACTORY)
        initializer = await self.encode_initializer()

        data = TxArgs(
            x=SafeContracts.SAFE_L2_V130.address,
            c=initializer,
            s=self.salt_nonce
        ).tuple()

        e = factory.encodeABI('createProxyWithNonce', args=data)

        tx_params = TxParams(
            to=factory.address,
            data=e,
            value=0
        )

        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)
        await asyncio.sleep(random.randint(2, 4))
        rcpt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if rcpt:
            return f"Success created Multisig Wallet "

        return "Failed | Creating Multisig Wallet"
