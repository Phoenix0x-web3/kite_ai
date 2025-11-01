import asyncio
import json
import random
import secrets
import time
from datetime import datetime, timedelta
from typing import Union

from loguru import logger
from web3 import Web3

from data.promts import Agents
from data.settings import Settings
from libs.base import Base
from libs.eth_async.client import Client
from libs.eth_async.data.models import RawContract
from modules.chain_api import BlockScout
from utils.browser import Browser
from utils.captcha.captcha_handler import CloudflareHandler
from utils.db_api.models import Wallet
from utils.db_api.wallet_api import db
from utils.logs_decorator import controller_log
from utils.query_json import query_to_json
from utils.retry import async_retry
from utils.twitter.twitter_client import TwitterOauthData

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
            url=f"{self.CHECKER_API}/api/v1/allocations/eligibility/{self.client.account.address.lower()}",
            headers=headers)

        return r.json().get('data') # .get('token_amount')

    @controller_log('Airdrop Checker')
    async def check_kite_ai(self):
        await self.sign_in()

        alloca = await self.get_token_allocation()

        if alloca.get('is_eligible'):

            self.wallet.eligible = alloca.get('is_eligible')
            self.wallet.airdrop = alloca.get('token_amount')

            return f'Token Allocation {alloca}'

        return f'Not Eligble | {alloca}'
