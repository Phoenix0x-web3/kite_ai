import asyncio
import json
import random
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Union

from eth_abi.abi import encode as abi_encode
from loguru import logger
from web3 import Web3
from web3.types import TxParams

from data.config import ABIS_DIR
from data.settings import Settings
from libs.base import Base
from libs.eth_async.client import Client
from libs.eth_async.data.models import RawContract, TokenAmount
from libs.eth_async.utils.files import read_json
from modules.helpers import generate_auth_token
from utils.browser import Browser
from utils.captcha.captcha_handler import CloudflareHandler
from utils.db_api.models import Wallet
from utils.db_api.wallet_api import db
from utils.logs_decorator import controller_log, action_log
from utils.retry import async_retry

SIMPLE_ACCOUNT_FACTORY_ABI = [
    {
        "type": "function",
        "name": "getAddress",
        "stateMutability": "view",
        "inputs": [
            {"name": "owner", "type": "address", "internalType": "address"},
            {"name": "salt", "type": "uint256", "internalType": "uint256"},
        ],
        "outputs": [
            {"name": "addr", "type": "address", "internalType": "address"}
        ],
    },
    {
        "type": "function",
        "name": "createAccount",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "owner", "type": "address", "internalType": "address"},
            {"name": "salt", "type": "uint256", "internalType": "uint256"},
        ],
        "outputs": [
            {"name": "account", "type": "address", "internalType": "address"}
        ],
    },
]

ACCOUNT_FACTORY = RawContract(
    title="SimpleAccountFactory",
    address=Web3.to_checksum_address("0x948f52524Bdf595b439e7ca78620A8f843612df3"),
    abi=SIMPLE_ACCOUNT_FACTORY_ABI,
)

salt  = "0x4b6f5b36bb7706150b17e2eecb6e602b1b90b94a4bf355df57466626a5cb897b"

class KiteAIPortal(Base):
    __module_name__ = "Kite AI API"

    FAUCET_API = "https://faucet.gokite.ai"
    TESTNET_API = "https://testnet.gokite.ai"
    BRIDGE_API = "https://bridge-backend.prod.gokite.ai"
    NEO_API = "https://neo.prod.gokite.ai"
    OZONE_API = "https://ozone-point-system.prod.gokite.ai"

    FAUCET_SITE_KEY = "6LeNaK8qAAAAAHLuyTlCrZD_U1UoFLcCTLoa_69T"
    TESTNET_SITE_KEY = "6Lc_VwgrAAAAALtx_UtYQnW-cFg8EPDgJ8QVqkaz"

    KITE_AI_SUBNET = "0xb132001567650917d6bd695d1fab55db7986e9a5"

    def __init__(self, client: Client, wallet: Wallet):
        self.client = client
        self.wallet = wallet
        self.session = Browser(wallet=wallet)
        self.base_headers = {
            "accept": "application/json, text/plain, */*",
            "origin": "https://testnet.gokite.ai",
            "referer": "https://testnet.gokite.ai/",
        }
        self.wallet.auth_token = self.wallet.auth_token
        self.eoa_address = wallet.eoa_address

    @staticmethod
    def _coerce_salt(salt: Union[int, str]) -> int:
        if isinstance(salt, int):
            return salt
        if isinstance(salt, str):
            return int(salt, 16) if salt.startswith("0x") else int(salt)
        raise TypeError("salt must be int or hex str")

    async def get_eoa_account(self):
        c = await self.client.contracts.get(ACCOUNT_FACTORY)
        salt_u256 = self._coerce_salt(salt)

        addr = await c.functions.getAddress(self.client.account.address, salt_u256).call()
        return addr



    @async_retry(retries=5, delay=3)
    async def sign_in(self, registration=False) -> dict:
        url = f"{self.TESTNET_API}/api/signin"

        headers = {
            **self.base_headers,
            "content-type": "application/json",
            "authorization": generate_auth_token(self.client.account.address)
        }

        data = {"eoa": self.client.account.address}
        if registration:
            data.update(
                {"aa_address": await self.get_eoa_account()}
            )

        r = await self.session.post(url=url, headers=headers, json=data, timeout=60)

        if r.json().get('error') == 'aa address is not found':
            return await self.sign_in(registration=True)

        r.raise_for_status()

        self.wallet.auth_token = r.json().get('data').get('access_token')
        self.wallet.eoa_address = r.json().get('data').get('aa_address')
        db.commit()

        return r.json()

        # raw_cookies = r.headers.get('set-cookie', [])
        # print(raw_cookies)
        # cookie_string = ""
        # if raw_cookies:
        #     from http.cookies import SimpleCookie
        #     cookie = SimpleCookie()
        #     cookie.load("\n".join(raw_cookies))
        #     cookie_string = "; ".join([f"{k}={m.value}" for k, m in cookie.items()])
        # print(cookie_string)

    @async_retry(retries=3, delay=3)
    async def get_user_info(self, registration=False) -> dict:
        if not self.wallet.auth_token:
            await self.sign_in()

        settings = Settings()

        headers = {
            **self.base_headers,
            "content-type": "application/json",
            "authorization": f"Bearer {self.wallet.auth_token}"
            }

        if registration:
            url = f"{self.OZONE_API}/auth"

            payload = {
                'registration_type_id': 1,
                'user_account_id': '',
                'user_account_name': '',
                'eoa_address': self.client.account.address,
                'smart_account_address': self.eoa_address,
                'referral_code': "",
            }

            invite_codes_from_db = [
                code[0] for code in db.all(Wallet.invite_code, Wallet.invite_code != "")
            ]

            all_invite_codes = list(set(settings.invite_codes + invite_codes_from_db))

            invite_code = random.choice(all_invite_codes) if all_invite_codes else ""

            if invite_code:
                payload["referral_code"] = invite_code

            r = await self.session.post(url=url, headers=headers, json=payload, timeout=60)

        url = f"{self.OZONE_API}/me"
        r = await self.session.get(url=url, headers=headers, timeout=60)

        if 'Invalid token' in r.json().get('error'):
            await self.sign_in()
            return await self.get_user_info()

        if 'User does not exist' in r.json().get('error'):
            return await self.get_user_info(registration=True)

        data = r.json().get('data')

        return data

    @async_retry(retries=3, delay=3)
    async def start_up_quiz(self) -> dict:
        url = f"{self.NEO_API}/v2/quiz/onboard/get"

        headers = {
            **self.base_headers,
            "content-type": "application/json",
            "authorization": f"Bearer {self.wallet.auth_token}"
        }

        data = {
            'eoa': self.client.account.address.lower()
        }
        r = await self.session.get(url=url, headers=headers, params=data, timeout=60)

        r.raise_for_status()
        data = r.json().get('data')

        return data

    @controller_log('Quiz Submit')
    async def submit(self, question_id, answer, finish=False, quiz_id: int = None):
        url = f"{self.NEO_API}/v2/quiz/onboard/submit"

        if quiz_id:
            url = f"{self.NEO_API}/v2/quiz/submit"

        headers = {
            **self.base_headers,
            "content-type": "application/json",
            "authorization": f"Bearer {self.wallet.auth_token}"
            }

        if not self.wallet.auth_token:
            return await self.sign_in()

        data = {
            'answer': answer,
            'eoa': self.client.account.address.lower() if not quiz_id else self.client.account.address,
            'finish': finish,
            'question_id': question_id,
        }

        if quiz_id:
            data.update({"quiz_id": quiz_id})

        r = await self.session.post(url=url, headers=headers, json=data, timeout=60)

        if r.json().get('data').get('result')  == 'RIGHT':
            return f'Success Answered '

        raise Exception(f'Failed to answer: {r.status_code} {r.text}')

    @controller_log('Portal Faucet')
    async def faucet(self):

        capmoster = CloudflareHandler(wallet=self.wallet)

        captcha_task = await capmoster.get_recaptcha_task_v2(
            websiteKey=self.TESTNET_SITE_KEY,
            websiteURL='https://testnet.gokite.ai/',
        )

        recaptcha_token = await capmoster.get_recaptcha_token(task_id=captcha_task)

        headers = {
            **self.base_headers,
            "content-type": "application/json",
            "Content-Length": "2",
            "authorization": f"Bearer {self.wallet.auth_token}",
            "x-recaptcha-token": recaptcha_token
        }

        json_data = {}

        url = f"{self.OZONE_API}/blockchain/faucet-transfer"
        r = await self.session.post(url=url, headers=headers, json=json_data, timeout=60)
        r.raise_for_status()

        return r.json().get('data')

    async def daily_quiz(self):

        url = f"{self.NEO_API}/v2/quiz/create"

        headers = {
            **self.base_headers,
            "content-type": "application/json",
            "authorization": f"Bearer {self.wallet.auth_token}"
            }
        now = datetime.utcnow()
        date = now.strftime("%Y-%m-%d")

        data = {
            'title': f'daily_quiz_{date}',
            'num': 1,
            'eoa': self.client.account.address,
        }

        quest = await self.session.post(url=url, headers=headers, json=data, timeout=60)
        if quest.json().get('data').get('status') == 0:

            url = f"{self.NEO_API}/v2/quiz/get"
            params = {
                "id": quest.json().get('data').get('quiz_id'),
                "eoa": self.client.account.address,
            }
            r = await self.session.get(url=url, headers=headers, params=params, timeout=60)

            r.raise_for_status()

            return r.json().get('data')

        return quest.get('data')

    async def get_balances(self):
        headers = {
            **self.base_headers,
            "authorization": f"Bearer {self.wallet.auth_token}",
        }

        url = f"{self.OZONE_API}/me/balance"

        r = await self.session.get(url=url, headers=headers, timeout=60)
        r.raise_for_status()

        return r.json().get('data').get('balances')


    async def withdrawal_from_portal(self, amount: int):
        url = f'{self.NEO_API}/v2/transfer'

        headers = {
            **self.base_headers,
            "content-type": "application/json",
            "Content-Length": "2",
            "authorization": f"Bearer {self.wallet.auth_token}",
        }

        params = {
            "eoa": self.client.account.address,
            "amount": amount,
            "type": 'native'
        }

        r = await self.session.post(url=url, headers=headers, params=params, json={}, timeout=60)
        r.raise_for_status()

        return r.json().get('data').get('packed_user_op').get('user_op_hash')


    async def get_badges(self):
        headers = {
            **self.base_headers,
            "authorization": f"Bearer {self.wallet.auth_token}",
        }

        url = f"{self.OZONE_API}/badges"

        r = await self.session.get(url=url, headers=headers, timeout=60)
        r.raise_for_status()

        return r.json().get('data')

    @controller_log('Claim Badge')
    async def claim_badge(self, badge_id):

        url = f"{self.OZONE_API}/badges/mint"

        headers = {
            **self.base_headers,
            "authorization": f"Bearer {self.wallet.auth_token}",
        }

        payload = {
            "badge_id": int(badge_id)
        }

        r = await self.session.post(url=url, headers=headers, json=payload, timeout=60)
        r.raise_for_status()

        return r.json().get('data')

    async def onboard_flow(self):
        user_info = await self.get_user_info()

        if not user_info['onboarding_quiz_completed']:

            quiz_info = await self.start_up_quiz()

            if quiz_info['quiz']['user_id'] == 'ONBOARD':
                questions = quiz_info['question']

                for q in questions:
                    finish = False
                    if 'Which subnet type in Kite AI provides' in q['content']:
                        finish = True

                    submit = await self.submit(question_id=q['question_id'], answer=q['answer'], finish=finish)
                    logger.debug(submit)
                    await asyncio.sleep(random.randint(3, 9))


        if not user_info['daily_quiz_completed']:
            daily_quest = await self.daily_quiz()
            quiz_id = daily_quest.get('quiz').get('quiz_id')
            questions = daily_quest.get('question')
            if len(questions) > 0:
                for q in questions:
                    await asyncio.sleep(random.randint(3, 9))
                    submit = await self.submit(question_id=q['question_id'], answer=q['answer'], finish=True, quiz_id=quiz_id)
                    logger.debug(submit)


        if user_info['faucet_claimable']:
            await self.faucet()

        return user_info

    @controller_log('Daily Quest')
    async def daily_quest_flow(self):
        daily_quest = await self.daily_quiz()
        quiz_id = daily_quest.get('quiz').get('quiz_id')
        questions = daily_quest.get('question')

        if len(questions) > 0:
            for q in questions:
                await asyncio.sleep(random.randint(3, 9))
                submit = await self.submit(question_id=q['question_id'], answer=q['answer'], finish=True,
                                           quiz_id=quiz_id)
                logger.debug(submit)

            return f'Success submit daily quest'
        else:
            raise Exception(f"Something wrong in daily quest | {daily_quest}")

    @controller_log('Onboard Flow')
    async def onboard_flow(self):
        quiz_info = await self.start_up_quiz()

        if quiz_info['quiz']['user_id'] == 'ONBOARD':
            questions = quiz_info['question']

            for q in questions:
                finish = False
                if 'Which subnet type in Kite AI provides' in q['content']:
                    finish = True

                submit = await self.submit(question_id=q['question_id'], answer=q['answer'], finish=finish)
                logger.debug(submit)
                await asyncio.sleep(random.randint(3, 9))

            return f"Success Onboarded"

        raise Exception(f"Something wrong | {quiz_info}")