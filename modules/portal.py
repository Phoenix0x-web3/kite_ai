import asyncio
import json
import random
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
from modules.helpers import generate_auth_token
from utils.browser import Browser
from utils.captcha.captcha_handler import CloudflareHandler
from utils.db_api.models import Wallet
from utils.db_api.wallet_api import db
from utils.logs_decorator import controller_log
from utils.query_json import query_to_json
from utils.retry import async_retry
from utils.twitter.twitter_client import TwitterOauthData

SIMPLE_ACCOUNT_FACTORY_ABI = [
    {
        "type": "function",
        "name": "getAddress",
        "stateMutability": "view",
        "inputs": [
            {"name": "owner", "type": "address", "internalType": "address"},
            {"name": "salt", "type": "uint256", "internalType": "uint256"},
        ],
        "outputs": [{"name": "addr", "type": "address", "internalType": "address"}],
    },
    {
        "type": "function",
        "name": "createAccount",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "owner", "type": "address", "internalType": "address"},
            {"name": "salt", "type": "uint256", "internalType": "uint256"},
        ],
        "outputs": [{"name": "account", "type": "address", "internalType": "address"}],
    },
]

ACCOUNT_FACTORY = RawContract(
    title="SimpleAccountFactory",
    address=Web3.to_checksum_address("0x948f52524Bdf595b439e7ca78620A8f843612df3"),
    abi=SIMPLE_ACCOUNT_FACTORY_ABI,
)

salt = "0x4b6f5b36bb7706150b17e2eecb6e602b1b90b94a4bf355df57466626a5cb897b"

STAKING_SUBNETS = {
    "Kite": {"address": "0x233b43fbe16b3c29df03914bac6a4b5e1616c3f3", "id": 496},
    "Bitmind": {"address": "0xda925c81137dd6e44891cdbd5e84bda3b4f81671", "id": 702},
    "AI Veronica": {"address": "0xb20f6f7d85f657c8cb66a7ee80799cf40f1d3533", "id": 699},
    "Bitte": {"address": "0x72ce733c9974b180bed20343bd1024a3f855ec0c", "id": 701},
}


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
        self.onchain_api = BlockScout(client=client, wallet=wallet)
        self.base_headers = {
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://testnet.gokite.ai",
            "Referer": "https://testnet.gokite.ai/",
        }
        self.auth_token = self.wallet.auth_token
        self.eoa_address = self.wallet.eoa_address
        self.paused = False

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
            "Content-Type": "application/json",
            "Authorization": generate_auth_token(self.client.account.address),
        }

        data = {"eoa": self.client.account.address}
        if registration:
            data.update({"aa_address": await self.get_eoa_account()})

        r = await self.session.post(url=url, headers=headers, json=data, timeout=60)

        if r.json().get("error") == "aa address is not found":
            return await self.sign_in(registration=True)

        r.raise_for_status()

        self.wallet.auth_token = r.json().get("data").get("access_token")
        self.wallet.eoa_address = r.json().get("data").get("aa_address")
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

        headers = {**self.base_headers, "Content-Type": "application/json", "Authorization": f"Bearer {self.wallet.auth_token}"}

        if registration:
            url = f"{self.OZONE_API}/auth"

            payload = {
                "registration_type_id": 1,
                "user_account_id": "",
                "user_account_name": "",
                "eoa_address": self.client.account.address,
                "smart_account_address": self.wallet.eoa_address,
                "referral_code": "",
            }

            if settings.invite_codes:  # use only settings if provided
                invite_code = random.choice(settings.invite_codes)
            else:
                invite_codes_from_db = [code[0] for code in db.all(Wallet.invite_code, Wallet.invite_code != "")]
                invite_code = random.choice(invite_codes_from_db) if invite_codes_from_db else ""

            if invite_code:
                payload["referral_code"] = invite_code

            r = await self.session.post(url=url, headers=headers, json=payload, timeout=60)

        url = f"{self.OZONE_API}/me"
        r = await self.session.get(url=url, headers=headers, timeout=60)

        if "Invalid token" in r.json().get("error"):
            await self.sign_in()
            return await self.get_user_info()

        if "User does not exist" in r.json().get("error"):
            return await self.get_user_info(registration=True)

        data = r.json().get("data")

        return data

    @async_retry(retries=3, delay=3)
    async def start_up_quiz(self) -> dict:
        url = f"{self.NEO_API}/v2/quiz/onboard/get"

        headers = {**self.base_headers, "Content-Type": "application/json", "Authorization": f"Bearer {self.wallet.auth_token}"}

        data = {"eoa": self.client.account.address.lower()}
        r = await self.session.get(url=url, headers=headers, params=data, timeout=60)

        r.raise_for_status()
        data = r.json().get("data")

        return data

    @controller_log("Quiz Submit")
    async def submit(self, question_id, answer, finish=False, quiz_id: int = None):
        url = f"{self.NEO_API}/v2/quiz/onboard/submit"

        if quiz_id:
            url = f"{self.NEO_API}/v2/quiz/submit"

        headers = {**self.base_headers, "Content-Type": "application/json", "Authorization": f"Bearer {self.wallet.auth_token}"}

        if not self.wallet.auth_token:
            return await self.sign_in()

        data = {
            "answer": answer,
            "eoa": self.client.account.address.lower() if not quiz_id else self.client.account.address,
            "finish": finish,
            "question_id": question_id,
        }

        if quiz_id:
            data.update({"quiz_id": quiz_id})

        r = await self.session.post(url=url, headers=headers, json=data, timeout=60)

        if r.json().get("data").get("result") == "RIGHT":
            return f"Success Answered "

        raise Exception(f"Failed to answer: {r.status_code} {r.text}")

    @controller_log("Portal Faucet")
    async def faucet(self):
        capmoster = CloudflareHandler(wallet=self.wallet)

        captcha_task = await capmoster.get_recaptcha_task_v2(
            websiteKey=self.TESTNET_SITE_KEY,
            websiteURL="https://testnet.gokite.ai/",
        )

        recaptcha_token = await capmoster.get_recaptcha_token(task_id=captcha_task)

        headers = {
            **self.base_headers,
            "Content-Type": "application/json",
            "Content-Length": "2",
            "Authorization": f"Bearer {self.wallet.auth_token}",
            "x-recaptcha-token": recaptcha_token,
        }

        json_data = {}

        url = f"{self.OZONE_API}/blockchain/faucet-transfer"
        r = await self.session.post(url=url, headers=headers, json=json_data, timeout=60)

        if r.status_code <= 202:
            return r.json().get("data")

        raise Exception(f"{r.status_code} | {r.json()}")

    @controller_log("Onchain Faucet")
    async def on_chain_faucet(self):
        capmoster = CloudflareHandler(wallet=self.wallet)

        captcha_task = await capmoster.get_recaptcha_task_v2(
            websiteKey=self.FAUCET_SITE_KEY,
            websiteURL="https://faucet.gokite.ai/",
        )

        recaptcha_token = await capmoster.get_recaptcha_token(task_id=captcha_task)

        headers = {
            "Content-Type": "application/json",
            "origin": "https://faucet.gokite.ai",
            "priority": "u=1, i",
            "referer": "https://faucet.gokite.ai/",
        }

        json_data = {
            "address": self.client.account.address,
            "token": "",
            "v2Token": recaptcha_token,
            "chain": "KITE",
            "couponId": "",
        }
        url = f"{self.FAUCET_API}/api/SendToken"

        r = await self.session.post(url=url, headers=headers, json=json_data, timeout=60)

        if r.status_code <= 202:
            self.wallet.next_faucet_time = datetime.now() + timedelta(minutes=1441)
            db.commit()
            return r.json().get("message")

        if r.status_code == 429:
            self.wallet.next_faucet_time = datetime.now() + timedelta(minutes=1441)
            db.commit()

            return f"Failed | Will retry after 24h | {r.json().get('message')}"

        raise Exception(f"Something wrong | {r.status_code} | {r.text}")

    async def daily_quiz(self):
        url = f"{self.NEO_API}/v2/quiz/create"

        headers = {**self.base_headers, "Content-Type": "application/json", "Authorization": f"Bearer {self.wallet.auth_token}"}
        now = datetime.utcnow()
        date = now.strftime("%Y-%m-%d")

        data = {
            "title": f"daily_quiz_{date}",
            "num": 1,
            "eoa": self.client.account.address,
        }

        quest = await self.session.post(url=url, headers=headers, json=data, timeout=60)
        if quest.json().get("data").get("status") == 0:
            url = f"{self.NEO_API}/v2/quiz/get"
            params = {
                "id": quest.json().get("data").get("quiz_id"),
                "eoa": self.client.account.address,
            }
            r = await self.session.get(url=url, headers=headers, params=params, timeout=60)

            r.raise_for_status()

            return r.json().get("data")

        return quest.get("data")

    async def get_balances(self):
        headers = {
            **self.base_headers,
            "Authorization": f"Bearer {self.wallet.auth_token}",
        }

        url = f"{self.OZONE_API}/me/balance"

        r = await self.session.get(url=url, headers=headers, timeout=60)
        r.raise_for_status()

        return r.json().get("data").get("balances").get("kite")

    async def withdrawal_from_portal(self, amount: int):
        url = f"{self.NEO_API}/v2/transfer"

        headers = {
            **self.base_headers,
            "Content-Type": "application/json",
            "Content-Length": "2",
            "Authorization": f"Bearer {self.wallet.auth_token}",
        }

        params = {"eoa": self.client.account.address, "amount": amount, "type": "native"}

        r = await self.session.post(url=url, headers=headers, params=params, json={}, timeout=60)

        r.raise_for_status()

        return r.json().get("data").get("user_op_hash")

    async def get_badges(self):
        headers = {
            **self.base_headers,
            "Authorization": f"Bearer {self.wallet.auth_token}",
        }

        url = f"{self.OZONE_API}/badges"

        r = await self.session.get(url=url, headers=headers, timeout=60)
        r.raise_for_status()

        return r.json().get("data")

    @controller_log("Claim Badge")
    async def claim_badge(self, badge_id):
        url = f"{self.OZONE_API}/badges/mint"

        headers = {
            **self.base_headers,
            "Authorization": f"Bearer {self.wallet.auth_token}",
        }

        payload = {"badge_id": int(badge_id)}

        r = await self.session.post(url=url, headers=headers, json=payload, timeout=60)
        r.raise_for_status()

        return r.json().get("data")

    async def onboard_flow(self):
        user_info = await self.get_user_info()

        if not user_info["onboarding_quiz_completed"]:
            quiz_info = await self.start_up_quiz()

            if quiz_info["quiz"]["user_id"] == "ONBOARD":
                questions = quiz_info["question"]

                for q in questions:
                    finish = False
                    if "Which subnet type in Kite AI provides" in q["content"]:
                        finish = True

                    submit = await self.submit(question_id=q["question_id"], answer=q["answer"], finish=finish)
                    logger.debug(submit)
                    await asyncio.sleep(random.randint(3, 9))

        if not user_info["daily_quiz_completed"]:
            daily_quest = await self.daily_quiz()
            quiz_id = daily_quest.get("quiz").get("quiz_id")
            questions = daily_quest.get("question")
            if len(questions) > 0:
                for q in questions:
                    await asyncio.sleep(random.randint(3, 9))
                    submit = await self.submit(question_id=q["question_id"], answer=q["answer"], finish=True, quiz_id=quiz_id)
                    logger.debug(submit)

        if user_info["faucet_claimable"]:
            await self.faucet()

        return user_info

    @controller_log("Daily Quest")
    async def daily_quest_flow(self):
        daily_quest = await self.daily_quiz()
        quiz_id = daily_quest.get("quiz").get("quiz_id")
        questions = daily_quest.get("question")

        if len(questions) > 0:
            for q in questions:
                await asyncio.sleep(random.randint(3, 9))
                submit = await self.submit(question_id=q["question_id"], answer=q["answer"], finish=True, quiz_id=quiz_id)
                logger.debug(f"{submit} | {q['content']}")

            return f"Success submit daily quest"
        else:
            raise Exception(f"Something wrong in daily quest | {daily_quest}")

    @controller_log("Onboard Flow")
    async def onboard_flow(self):
        quiz_info = await self.start_up_quiz()

        if quiz_info["quiz"]["user_id"] == "ONBOARD":
            questions = quiz_info["question"]

            for q in questions:
                finish = False
                if "Which subnet type in Kite AI provides" in q["content"]:
                    finish = True

                submit = await self.submit(question_id=q["question_id"], answer=q["answer"], finish=finish)
                logger.debug(f"{submit} | {q['content']}")
                await asyncio.sleep(random.randint(3, 9))

            return f"Success Onboarded"

        raise Exception(f"Something wrong | {quiz_info}")

    async def get_stake_amounts(self):
        url = f"{self.OZONE_API}/me/staked"

        headers = {
            **self.base_headers,
            "Authorization": f"Bearer {self.wallet.auth_token}",
        }

        r = await self.session.get(url=url, headers=headers, timeout=60)
        r.raise_for_status()

        return r.json().get("data").get("total_staked_amount")

    @controller_log("Portal Staking")
    async def stake(self, amount: int):
        agent = random.choice(list(STAKING_SUBNETS.keys()))

        balance = await self.get_balances()
        if balance < amount:
            return "Failed to Stake, low balance"

        url = f"{self.OZONE_API}/subnet/delegate"

        payload = {"amount": amount, "subnet_address": STAKING_SUBNETS[agent]["address"]}
        headers = {
            **self.base_headers,
            "Authorization": f"Bearer {self.wallet.auth_token}",
        }

        r = await self.session.post(url=url, headers=headers, json=payload, timeout=60)

        if r.status_code == 200:
            res = r.json().get("data").get("tx_hash")
            return f"Success | Staked to {agent} {amount} KITE | tx_hash: {res}"

        raise Exception(f"Failed to stake | {r.status_code} | {r.text}")

    async def check_staked_balance(self):
        result = []

        if not self.wallet.auth_token:
            await self.sign_in()

        for agent in STAKING_SUBNETS:
            id = STAKING_SUBNETS[agent]["id"]

            url = f"{self.OZONE_API}/subnet/{id}/staked-info?id={id}"

            headers = {
                **self.base_headers,
                "Authorization": f"Bearer {self.wallet.auth_token}",
            }

            r = await self.session.get(url=url, headers=headers, timeout=60)

            if r.status_code == 200:
                amount = r.json().get("data").get("my_staked_amount")
                if amount > 0:
                    result.append(agent)

            await asyncio.sleep(3, 10)

        return result

    @controller_log("Claim Staking Rewards")
    async def claim_staking_rewards(self, agent):
        url = f"{self.OZONE_API}/subnet/claim-rewards"

        payload = {"subnet_address": STAKING_SUBNETS[agent]["address"]}

        headers = {
            **self.base_headers,
            "Authorization": f"Bearer {self.wallet.auth_token}",
        }

        r = await self.session.post(url=url, headers=headers, json=payload, timeout=60)

        if r.status_code == 200:
            tx_hash = r.json().get("data").get("tx_hash")
            claim_amount = r.json().get("data").get("claim_amount")
            return f"Success | Claimed {claim_amount} KITE from {agent} subnet| tx_hash: {tx_hash}"

        raise Exception(f"Failed to claim | {r.status_code} | {r.text}")

    async def unstake(self):
        pass

    async def generate_ai_request_payload(self, service: str, question: str, answer: str):
        try:
            payload = {
                "address": self.wallet.eoa_address,
                "input": [{"type": "text/plain", "value": question}],
                "output": [{"type": "text/plain", "value": answer}],
                "service_id": service,
            }

            return payload
        except Exception as e:
            raise Exception(f"Generate Receipt Payload Failed: {str(e)}")

    async def generate_ai_inference_payload(self, service: str, question: str):
        try:
            payload = {
                "service_id": service,
                "body": {"message": question, "stream": True},
                "stream": True,
                "subnet": "kite_ai_labs",
            }

            return payload
        except Exception as e:
            raise Exception(f"Generate Inference Payload Failed: {str(e)}")

    async def parse_ai_answer(self, answer):
        if hasattr(answer, "text") and isinstance(answer.text, str):
            s = answer.text
        elif hasattr(answer, "content"):
            s = answer.content.decode("utf-8", "ignore")
        elif isinstance(answer, (bytes, bytearray)):
            s = answer.decode("utf-8", "ignore")
        else:
            s = str(answer)

        result = []
        for raw_line in s.splitlines():
            line = raw_line.strip()
            if not line.startswith("data:"):
                continue
            if line == "data: [DONE]":
                break

            try:
                payload = json.loads(line[len("data:") :].strip())
                choices = payload.get("choices") or [{}]
                delta = choices[0].get("delta", {})
                content = delta.get("content")
                if content:
                    result.append(content)
            except json.JSONDecodeError:
                continue

        return "".join(result).strip()

    async def parse_ai_answer_(self, answer):
        result = ""
        for line in answer.content:
            line = line.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue

            if line == "data: [DONE]":
                return result.strip()

            try:
                json_data = json.loads(line[len("data:") :].strip())
                delta = json_data.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content")
                if content:
                    result += content

            except json.JSONDecodeError:
                continue

        return result.strip()

    async def submit_receipt(self, service, question, answer):
        url = f"{self.NEO_API}/v2/submit_receipt"

        payload = await self.generate_ai_request_payload(service, question, answer)

        headers = {
            **self.base_headers,
            "Content-Type": "application/json",
            # "Content-Length": str(len(data)),
            "Authorization": f"Bearer {self.wallet.auth_token}",
        }

        r = await self.session.post(url=url, headers=headers, json=payload, timeout=90)
        r.raise_for_status()

        return r.json().get("data")

    @async_retry(retries=5)
    async def get_inference(self, inference_id):
        url = f"{self.NEO_API}/v1/inference?id={inference_id}"

        headers = {
            **self.base_headers,
            "Authorization": f"Bearer {self.wallet.auth_token}",
        }

        r = await self.session.get(url=url, headers=headers, timeout=90)

        r.raise_for_status()
        tx_hash = r.json().get("data", {}).get("tx_hash", "")

        if not tx_hash:
            raise Exception(f"no tx hash")

        return tx_hash

    async def agent_commutication(self, service, question):
        url = f"{self.OZONE_API}/agent/inference"

        payload = await self.generate_ai_inference_payload(service, question)

        headers = {
            **self.base_headers,
            "accept": "text/event-stream",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.wallet.auth_token}",
        }

        r = await self.session.post(url=url, headers=headers, json=payload, timeout=90)

        if r.status_code <= 202:
            answer = await self.parse_ai_answer(answer=r)
            return answer

        if r.status_code == 429:
            self.wallet.next_ai_conversation_time = datetime.now() + timedelta(minutes=1441)
            self.paused = True
            db.commit()

        raise Exception(f"{self.wallet} | {r.status_code} | {r.text}")

    @controller_log("AI Agent Dialog")
    async def ai_agent_chat_flow(self):
        if self.paused:
            return f"AI Agent rate limit"

        if not self.wallet.auth_token:
            await self.sign_in()

        await asyncio.sleep(1)
        promts = Agents()

        agent = random.choice(promts.agents)

        service = agent["service"]
        agent_name = agent["agent"]
        questions: list = agent["questions"]

        q = random.choice(questions)
        questions.remove(q)

        if agent_name == "Sherlock":
            tx = await self.onchain_api.get_random_tx()
            if len(tx) > 0:
                tx = random.choice(tx)
                q = q + " " + tx.get("hash")

        try:
            logger.debug(f"{self.wallet} | {self.__module_name__} | Agent: {agent_name} | Question: {q}")

            communicate = await self.agent_commutication(service=service, question=q)
            logger.debug(f"{self.wallet} | {self.__module_name__} | Agent: {agent_name} | Answer: {communicate}")

            submit_receipt = await self.submit_receipt(service=service, question=q, answer=communicate)

            if not submit_receipt.get("id"):
                raise Exception(f"Conversation ID is not received")

            await asyncio.sleep(random.randint(3, 5))

            finish = await self.get_inference(inference_id=submit_receipt["id"])

            if finish:
                return f"Agent: {agent_name} | Conversation Completed tx_hash: {finish}"

        except Exception as e:
            raise Exception(f"Agent{agent_name} | {e}")

    async def get_twitter_link(self):
        if not self.wallet.auth_token:
            await self.sign_in()

        return f"https://x.com/i/api/2/oauth2/authorize?client_id=YW1nN2RHYmtEVV9odHNOSEZ2SEE6MTpjaQ&code_challenge=challenge&code_challenge_method=plain&redirect_uri=https%3A%2F%2Ftestnet.gokite.ai%2Ftwitter&response_type=code&scope=tweet.read%20users.read&state=state"

    async def bind_twitter(self, callback: TwitterOauthData):
        if not self.wallet.auth_token:
            await self.sign_in()

        r = await self.session.get(url=callback.callback_url, allow_redirects=False)

        location = r.headers.get("location")

        r = await self.session.get(url=location)

        query_data = query_to_json(location)

        cookies = {"user_session_id": self.wallet.auth_token}

        headers = {**self.base_headers, "referer": f"{self.TESTNET_API}/twitter"}

        r = await self.session.post(
            url=f"{self.TESTNET_API}/twitter?token={query_data.get('token')}",
            headers=headers,
            cookies=cookies,
            json={},
        )
        return r.json()

    async def get_discord_link(self):
        return f"https://discord.com/api/v9/oauth2/authorize?client_id=1355842034900013246&response_type=code&redirect_uri=https%3A%2F%2Ftestnet.gokite.ai%2Fdiscord&scope=identify&integration_type=0"

    async def bind_discord(self, callback: str):
        if not self.wallet.auth_token:
            await self.sign_in()

        headers = {"referer": "https://discord.com/"}

        r = await self.session.get(url=callback, headers=headers, allow_redirects=False)

        location = r.headers.get("location")

        r = await self.session.get(url=location)

        query_data = query_to_json(location)

        await asyncio.sleep(1, 3)

        cookies = {"user_session_id": self.wallet.auth_token}

        headers = {**self.base_headers, "referer": f"{self.TESTNET_API}/discord"}
        r = await self.session.post(
            url=f"{self.TESTNET_API}/discord?token={query_data.get('token')}",
            headers=headers,
            cookies=cookies,
            json={},
        )
        return r.json()

    async def get_twitter_tasks(self, user_data):
        user_data = user_data.get("social_accounts").get("twitter").get("action_types")
        # disabled task
        twitter_tasks = [task for task in user_data if not task["id"] == 17]

        twitter_tasks = [task for task in twitter_tasks if not task["is_completed"]]

        return twitter_tasks
