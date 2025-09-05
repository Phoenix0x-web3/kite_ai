import asyncio
import random
from datetime import datetime

from loguru import logger

from data.settings import Settings
from libs.eth_async.client import Client
from libs.base import Base
from modules.onchain import KiteOnchain
from modules.portal import KiteAIPortal

from utils.db_api.models import Wallet
from utils.db_api.wallet_api import db
from utils.db_update import update_points_invites
from utils.logs_decorator import controller_log


class Controller:

    def __init__(self, client: Client, wallet: Wallet):
        self.client = client
        self.wallet = wallet
        self.base = Base(client=client, wallet=wallet)
        self.portal = KiteAIPortal(client=client, wallet=wallet)
        self.onchain = KiteOnchain(client=client, wallet=wallet)

    @controller_log('Update Points')
    async def update_db_by_user_info(self):
        user_data = await self.portal.get_user_info()

        total_points = user_data.get('profile').get('total_xp_points')
        invite_code = user_data.get('profile').get('referral_code')

        logger.info(f"{self.wallet} | Total Points: [{total_points}] | Invite Code: [{invite_code}]")
        return await update_points_invites(self.wallet.private_key, total_points, invite_code)

    async def onchain_faucet(self):
        pass

    @controller_log('Twitter Tasks')
    async def twitter_tasks(self):
        pass

    async def discord_tasks(self):
        pass

    async def onboard_to_portal(self, onchain_faucet: False):
        user_info = await self.portal.get_user_info()

        if not user_info['onboarding_quiz_completed']:
            result = await self.portal.onboard_flow()
            if 'Failed' not in result:
                logger.success(result)

        if onchain_faucet:
            result = await self.portal.on_chain_faucet()
            if 'Failed' not in result:
                logger.success(result)
        else:
            if user_info['faucet_claimable']:
                result = await self.portal.faucet()
                if 'Failed' not in result:
                    logger.success(result)

        return result


    async def build_actions(self):

        settings = Settings()

        actions = []

        build_actions = []

        swaps_count = random.randint(settings.swaps_count_min, settings.swaps_count_max)
        ai_dialogs_count = random.randint(settings.ai_dialogs_count_min, settings.ai_dialogs_count_max)

        balance = await self.client.wallet.balance()

        if float(balance.Ether) == 0:

            onboard_actions = [
                lambda: self.onboard_to_portal(onchain_faucet=True),
                lambda: self.onboard_to_portal(onchain_faucet=False)
                               ]

            onboard = random.choice(onboard_actions)

            try:
                onboard = await onboard()

                await asyncio.sleep(10)

                if 'Failed' not in onboard:
                    logger.success(onboard)
                    balance = await self.client.wallet.balance()

                else:
                    raise Exception(f"{self.wallet} | Controller | {onboard}")

            except:
                raise RuntimeError(f"{self.wallet} | Controller | {onboard} | Actions stopped")

        user_info = await self.portal.get_user_info()

        if not user_info['onboarding_quiz_completed']:
            actions.append(lambda: self.portal.onboard_flow())

        if not user_info['daily_quiz_completed']:
            build_actions.append(lambda: self.portal.daily_quest_flow())

        if user_info['faucet_claimable']:
            build_actions.append(lambda: self.portal.faucet())

        badges = await self.portal.get_badges()
        badges = [badge for badge in badges if badge["isEligible"]]

        user_badges = user_info["profile"]["badges_minted"]

        if not user_badges:
            build_actions.extend(
                [lambda: self.portal.claim_badge(badge_id=badge["collectionId"]) for badge in badges]
            )

        now = datetime.now()

        if self.wallet.next_faucet_time <= now:
            build_actions.append(lambda: self.portal.on_chain_faucet())

        if not await self.onchain.check_bridge_status():
            build_actions.append(lambda: self.onchain.controller(action='bridge'))

        if self.wallet.next_ai_conversation_time <= now:
            build_actions += [lambda: self.portal.ai_agent_chat_flow() for _ in range(ai_dialogs_count)]

        if float(balance.Ether) > 0:
            build_actions += [lambda: self.onchain.controller(action='swap') for _ in range(swaps_count)]

        # portal_balance = await self.portal.get_balances()
        #
        # if portal_balance.get('kite') > 0.01:
        #     build_actions.append(lambda: self.portal.withdrawal_from_portal(amount=1))

        random.shuffle(build_actions)
        actions += build_actions
        return actions

