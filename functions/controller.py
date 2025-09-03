import asyncio
import random

from loguru import logger

from libs.eth_async.client import Client
from libs.base import Base
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

    @controller_log('Update Points')
    async def update_db_by_user_info(self):
        user_data = await self.portal.get_user_info()

        total_points = user_data.get('profile').get('total_xp_points')
        invite_code = user_data.get('profile').get('referral_code')

        logger.info(f"{self.wallet} | Total Points: [{total_points}] | Invite Code: [{invite_code}]")
        return await update_points_invites(self.wallet.private_key, total_points, invite_code)

    async def onchain_faucet(self):
        pass

    async def build_actions(self):

        actions = []

        build_actions = []
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

        # portal_balance = await self.portal.get_balances()
        #
        # if portal_balance.get('kite') > 0.01:
        #     build_actions.append(lambda: self.portal.withdrawal_from_portal(amount=1))

        random.shuffle(build_actions)
        actions += build_actions
        return actions

