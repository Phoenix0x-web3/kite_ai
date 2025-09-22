import asyncio
import json
import random
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional

from eth_abi.abi import encode as abi_encode
from eth_keys.utils.module_loading import split_at_longest_importable_path
from loguru import logger
from web3 import Web3
from web3.types import TxParams

from data.config import ABIS_DIR
from data.settings import Settings
from libs.base import Base
from libs.eth_async.client import Client
from libs.eth_async.data.models import RawContract, TokenAmount, DefaultABIs, TxArgs
from libs.eth_async.utils.files import read_json
from utils.browser import Browser
from utils.db_api.models import Wallet
from utils.logs_decorator import controller_log
from utils.retry import async_retry

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
ABI = [
    # ---------------- Router (V2-style) ----------------
    {
        "type": "function",
        "name": "factory",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "address"}],
    },

    # ---------------- Factory V2 ----------------
    {
        "type": "function",
        "name": "getPair",
        "stateMutability": "view",
        "inputs": [
            {"name": "tokenA", "type": "address"},
            {"name": "tokenB", "type": "address"},
        ],
        "outputs": [{"name": "pair", "type": "address"}],
    },
    {
        "type": "function",
        "name": "allPairsLength",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}],
    },

    # ---------------- Factory V3 ----------------
    {
        "type": "function",
        "name": "getPool",
        "stateMutability": "view",
        "inputs": [
            {"name": "tokenA", "type": "address"},
            {"name": "tokenB", "type": "address"},
            {"name": "fee", "type": "uint24"},
        ],
        "outputs": [{"name": "pool", "type": "address"}],
    },

    # ---------------- Pair (Uniswap V2-like) ----------------
    {
        "type": "function",
        "name": "token0",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "address"}],
    },
    {
        "type": "function",
        "name": "token1",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "address"}],
    },
    {
        "type": "function",
        "name": "getReserves",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [
            {"name": "reserve0", "type": "uint112"},
            {"name": "reserve1", "type": "uint112"},
            {"name": "blockTimestampLast", "type": "uint32"},
        ],
    },

    # ---------------- Bridge/Router (send + initiate) ----------------
    {
        "type": "function",
        "name": "send",
        "stateMutability": "payable",
        "inputs": [
            {"name": "_destChainId", "type": "uint256"},
            {"name": "_recipient",   "type": "address"},
            {"name": "_amount",      "type": "uint256"},
        ],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "initiate",
        "stateMutability": "payable",
        "inputs": [
            {"name": "token",  "type": "address", "internalType": "address"},
            {"name": "amount", "type": "uint256", "internalType": "uint256"},
            {
                "name": "instructions",
                "type": "tuple",
                "internalType": "struct Instructions",
                "components": [
                    {"name": "sourceId",             "type": "uint256", "internalType": "uint256"},
                    {"name": "receiver",             "type": "address", "internalType": "address"},
                    {"name": "payableReceiver",      "type": "bool",    "internalType": "bool"},
                    {"name": "rollbackReceiver",     "type": "address", "internalType": "address"},
                    {"name": "rollbackTeleporterFee","type": "uint256", "internalType": "uint256"},
                    {"name": "rollbackGasLimit",     "type": "uint256", "internalType": "uint256"},
                    {
                        "name": "hops",
                        "type": "tuple[]",
                        "internalType": "struct Hop[]",
                        "components": [
                            {"name": "action",            "type": "uint8",    "internalType": "enum Action"},
                            {"name": "requiredGasLimit",  "type": "uint256",  "internalType": "uint256"},
                            {"name": "recipientGasLimit", "type": "uint256",  "internalType": "uint256"},
                            {"name": "trade",             "type": "bytes",    "internalType": "bytes"},
                            {
                                "name": "bridgePath",
                                "type": "tuple",
                                "internalType": "struct BridgePath",
                                "components": [
                                    {"name": "bridgeSourceChain",      "type": "address", "internalType": "address"},
                                    {"name": "sourceBridgeIsNative",   "type": "bool",    "internalType": "bool"},
                                    {"name": "bridgeDestinationChain", "type": "address", "internalType": "address"},
                                    {"name": "cellDestinationChain",   "type": "address", "internalType": "address"},
                                    {"name": "destinationBlockchainID","type": "bytes32", "internalType": "bytes32"},
                                    {"name": "teleporterFee",          "type": "uint256", "internalType": "uint256"},
                                    {"name": "secondaryTeleporterFee", "type": "uint256", "internalType": "uint256"},
                                ],
                            },
                        ],
                    },
                ],
            },
        ],
        "outputs": [],
    },
]
MULTICALL3 = RawContract(
    title="Multicall3",
    address="0x88E564D3cFf40d99C76e43434Ce293B6f545F024",
    abi=ABI,
)


KITE_BRIDGE_ROUTER = RawContract(
    title='KiteBridgeRouter',
    address='0x0BBB7293c08dE4e62137a557BC40bc12FA1897d6',
    abi=ABI

)
KITE_SWAP_ROUTER_NATIVE = RawContract(
    title="KiteSwapRouter",
    address=Web3.to_checksum_address("0x04CfcA82fDf5F4210BC90f06C44EF25Bf743D556"),
    abi=ABI
)

KITE_SWAP_FACTORY = RawContract(
    title="Factory",
    address=Web3.to_checksum_address("0x147f235Dde1adcB00Ef8E2D10D98fEd9a091284D"),
    abi=ABI,
)

class Contracts:
    KITE = RawContract(
        title="KITE",
        address=ZERO_ADDRESS,
        abi=DefaultABIs.Token
    )

    USDT = RawContract(
        title="USDT",
        address=Web3.to_checksum_address("0x0fF5393387ad2f9f691FD6Fd28e07E3969e27e63"),
        abi=DefaultABIs.Token
    )

    WKITE = RawContract(
        title="WKITE",
        address=Web3.to_checksum_address("0x3bC8f037691Ce1d28c0bB224BD33563b49F99dE8"),
        abi=ABI,
    )

BRIDGE_ROUTER = RawContract(
    title="BridgeRouter",
    address=Web3.to_checksum_address("0xD1bd49F60A6257dC96B3A040e6a1E17296A51375"),
    abi=ABI,
)

DEST_BLOCKCHAIN_ID = "0x6715950e0aad8a92efaade30bd427599e88c459c2d8e29ec350fc4bfb371a114"

class KiteOnchain(Base):
    __module_name__ = "Kite Onchain"

    def __init__(self, client: Client, wallet: Wallet):
        self.client = client
        self.wallet = wallet
        self.session = Browser(wallet=wallet)

    async def _encode_trade_bytes(self, token_in: str, token_out: str, amount_out: TokenAmount, amount_out_min: TokenAmount) -> bytes:

        if token_in == Contracts.KITE.address:
            token_in = Contracts.WKITE.address

        if token_out == Contracts.KITE.address:
            token_out = Contracts.WKITE.address

        return abi_encode(
            ["uint8", "uint8", "uint256", "uint256", "address", "address", "address"],
            [32, 96, amount_out.Wei, amount_out_min.Wei, Web3.to_checksum_address("0x0000000000000000000000000000000000000002"),
             Web3.to_checksum_address(token_in),
             Web3.to_checksum_address(token_out)]
        )

    async def _build_instructions(
        self,
        receiver: str,
        swap_native_to_erc20: bool,
        token_in: str,
        token_out: str,
        amount_out: TokenAmount,
        amount_out_min: TokenAmount
    ) -> tuple:
        trade_hex: bytes = await self._encode_trade_bytes(token_in, token_out, amount_out=amount_out, amount_out_min=amount_out_min)

        payable_receiver = not swap_native_to_erc20

        hop = (
            3,                 # action
            2_620_000,         # requiredGasLimit
            2_120_000,         # recipientGasLimit
            trade_hex,         # trade bytes
            (                  # bridgePath
                ZERO_ADDRESS,                  # bridgeSourceChain
                False,                         # sourceBridgeIsNative
                ZERO_ADDRESS,                  # bridgeDestinationChain
                KITE_SWAP_ROUTER_NATIVE.address,  # cellDestinationChain
                DEST_BLOCKCHAIN_ID,            # destinationBlockchainID
                0,                             # teleporterFee
                0                              # secondaryTeleporterFee
            )
        )

        return (
            1,                                  # sourceId
            Web3.to_checksum_address(receiver), # receiver
            payable_receiver,                   # payableReceiver
            Web3.to_checksum_address(receiver), # rollbackReceiver
            0,                                  # rollbackTeleporterFee
            500_000,                            # rollbackGasLimit
            [hop],                              # hops[]
        )

    @controller_log("Deposit")
    async def deposit(self, to: str, amount: TokenAmount) -> str:

        tx = await self.client.transactions.sign_and_send(TxParams(
            to=Web3.to_checksum_address(to),
            value=amount.Wei,
            data="0x"
        ))
        rcpt = await tx.wait_for_receipt(client=self.client, timeout=300)
        if rcpt:
            return f"Success | Deposit {amount.Ether:.6f} native to {to}"
        return f"Failed | Deposit {amount.Ether:.6f} native to {to}"

    async def correct_tokens_position(self,
                                      from_token: RawContract,
                                      to_token: RawContract):

        uint160_token0 = int(Web3.to_checksum_address(from_token.address), 16)
        uint160_token1 = int(Web3.to_checksum_address(to_token.address), 16)

        if uint160_token0 > uint160_token1:
            return to_token, from_token
        else:
            return from_token, to_token

    async def get_pool_address(self, from_token: RawContract, to_token: RawContract):

        contract_pool = await self.client.contracts.get(contract_address=KITE_SWAP_FACTORY)

        data = TxArgs(
            tokenA=from_token.address,
            tokenB=to_token.address
        ).tuple()

        try:
            pool_address = await contract_pool.functions.getPair(*data).call()
            if pool_address == '0x0000000000000000000000000000000000000000':
                return None
            else:
                return RawContract(
                    title='POOL',
                    address=pool_address,
                    abi=ABI
                )
        except Exception as e:
            logger.exception(e)
            return None

    async def get_price_pool(self,
                             from_token: RawContract,
                             to_token: RawContract,
                            ):

        from_token, to_token = await self.correct_tokens_position(
            from_token=from_token,
            to_token=to_token)

        pool_contract = await self.get_pool_address(from_token=from_token, to_token=to_token)

        pair = await self.client.contracts.get(contract_address=pool_contract)

        token0 = (await pair.functions.token0().call()).lower()
        token1 = (await pair.functions.token1().call()).lower()

        r0, r1, _ = await pair.functions.getReserves().call()

        decimals = 18

        if from_token.address.lower() == token0 and to_token.address.lower() == token1:
            price = (Decimal(r1) / (Decimal(10) ** decimals)) / (Decimal(r0) / (Decimal(10) ** decimals))
            return float(price), token0, token1

        if from_token.address.lower() == token1 and to_token.address.lower() == token0:
            price = (Decimal(r0) / (Decimal(10) ** decimals)) / (Decimal(r1) / (Decimal(10) ** decimals))
            return float(price), token1, token0

    @controller_log('Tesseract | Swap')
    async def _swap(self,
                    amount: TokenAmount,
                    from_token: RawContract,
                    to_token: RawContract,
                    slippage: float = 3.0,
                    fee: int = 500):

        c = await self.client.contracts.get(contract_address=KITE_SWAP_ROUTER_NATIVE)

        from_token_is_kite = from_token.address.upper() == Contracts.KITE.address.upper()
        if from_token_is_kite: from_token = Contracts.WKITE

        to_token_is_kite = to_token.address.upper() == Contracts.KITE.address.upper()
        if to_token_is_kite: to_token = Contracts.WKITE

        price, token0, token1 = await self.get_price_pool(from_token, to_token)

        if token0 == from_token.address.lower():
            amount_out = TokenAmount(amount=float(amount.Ether) * price)
            amount_out_min = TokenAmount(
                amount=float(amount.Ether) * price * (100 - slippage) / 100
            )

        if token1 == from_token.address.lower():
            amount_out = TokenAmount(amount=float(amount.Ether) / price )
            amount_out_min = TokenAmount(
                amount=float(amount.Ether) / price * (100 - slippage) / 100,
            )

        logger.debug(
            f'{self.wallet} | {self.__module_name__} | Tesseract | Trying to swap {amount.Ether:.5f} {from_token.title} to '
            f'{amount_out_min.Ether:.5f} {to_token.title}')

        instructions = await self._build_instructions(
            receiver=self.client.account.address,
            swap_native_to_erc20=from_token_is_kite,
            token_in=from_token.address,
            token_out=to_token.address,
            amount_out=amount_out,
            amount_out_min=amount_out_min
        )

        args = (
            from_token.address,
            amount.Wei,
            instructions
        )

        data = c.encode_abi("initiate", args=args)

        if not from_token_is_kite:
            ok = await self.approve_interface(
                token_address=from_token.address,
                spender=c.address,
                amount=None
            )
            if not ok:
                return "Failed | approve"

            await asyncio.sleep(random.randint(2, 5))

        tx_params = TxParams(
            to=c.address,
            data=data,
            value=int(amount.Wei) if from_token_is_kite else 0
        )

        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)
        await asyncio.sleep(random.randint(2, 4))
        rcpt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if rcpt:
            return f"Success swap {amount} {from_token.title} to {amount_out} {to_token.title}"

        return "Failed | Swap"

    async def  current_balances(self, tokens: list) -> dict:
        balances = {}

        for token in tokens:
            if token == Contracts.KITE:
                balance = await self.client.wallet.balance()
            else:
                balance = await self.client.wallet.balance(token=token)

            if balance.Ether > 0.1:
                balances[token] = balance

        return balances

    async def controller(self, action: str):

        tokens = [
            Contracts.KITE,
            Contracts.USDT
        ]

        balances = await self.current_balances(tokens=tokens)

        if not balances:
            return f"{self.wallet} | {self.__module_name__} | No balances try to faucet first"

        if all(float(value.Ether) == 0 for value in balances.values()):
            return f'{self.wallet} | {self.__module_name__} | Failed | No balance in all tokens, try to faucet first'

        from_token = random.choice(list(balances.keys()))

        amount = balances[from_token]

        settings = Settings()

        percent = random.randint(settings.swaps_percent_min, settings.swaps_percent_max) / 100

        amount = TokenAmount(amount=float(amount.Ether) * percent, decimals=amount.decimals)

        if action == 'bridge':
            return await self.bridge_send(
                token=from_token,
                dest_chain_id=84532,
                amount=amount
            )

        if action == 'swap':
            tokens.remove(from_token)
            to_token = random.choice(tokens)

            return await self._swap(
                from_token=from_token,
                to_token=to_token,
                amount=amount
            )

    async def check_bridge_status(self):
        headers = {
            'origin': 'https://bridge.prod.gokite.ai',
            'priority': 'u=1, i',
            'referer': 'https://bridge.prod.gokite.ai/',
         }

        params = {
            'address': self.client.account.address,
        }

        r = await self.session.get(
            url = 'https://bridge-backend.prod.gokite.ai/check-interaction',
            params=params,
            headers=headers)

        return r.json().get('data').get('has_interacted')

    @controller_log("Bridge send")
    async def bridge_send(
        self,
        token: RawContract | str,
        dest_chain_id: int,
        amount: TokenAmount
    ) -> str:

        is_native = token == Contracts.KITE

        if is_native:
            c = await self.client.contracts.get(KITE_BRIDGE_ROUTER)

        else:
            c = await self.client.contracts.get(BRIDGE_ROUTER)

        if not is_native:
            ok = await self.approve_interface(
                token_address=token.address,
                spender=c.address,
                amount=None
            )

            if not ok:
                return "Failed | approve() for bridge"

            await asyncio.sleep(random.randint(2, 5))

        data = c.encode_abi("send", args=(int(dest_chain_id), self.client.account.address, int(amount.Wei)))

        tx = await self.client.transactions.sign_and_send(TxParams(
            to=c.address,
            data=data,
            value=amount.Wei if is_native else 0
        ))

        await asyncio.sleep(random.randint(2, 4))

        rcpt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if rcpt:
            return f"Success | Bridge send {amount} to chainId={dest_chain_id}"

        return "Failed | Bridge send"

