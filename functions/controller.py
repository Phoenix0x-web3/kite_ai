import asyncio
import random
from datetime import datetime

from loguru import logger

from data.settings import Settings
from libs.eth_async.client import Client
from libs.base import Base
from modules.multisig import Safe
from modules.onchain import KiteOnchain
from modules.portal import KiteAIPortal

from utils.db_api.models import Wallet
from utils.db_api.wallet_api import db
from utils.db_update import update_points_invites
from utils.discord.discord import DiscordOAuth, DiscordStatus, DiscordInviter
from utils.logs_decorator import controller_log
from utils.twitter.twitter_client import TwitterClient, TwitterStatuses


class Controller:

    def __init__(self, client: Client, wallet: Wallet):
        self.client = client
        self.wallet = wallet
        self.base = Base(client=client, wallet=wallet)
        self.twitter = TwitterClient(user=self.wallet)
        self.portal = KiteAIPortal(client=client, wallet=wallet)
        self.onchain = KiteOnchain(client=client, wallet=wallet)
        self.safe = Safe(client=client, wallet=wallet)

    @controller_log('Update Points')
    async def update_db_by_user_info(self):
        user_data = await self.portal.get_user_info()

        total_points = user_data.get('profile').get('total_xp_points')
        invite_code = user_data.get('profile').get('referral_code')
        rank = user_data.get('profile').get('rank')

        logger.info(f"{self.wallet} | Total Points: [{total_points}] | Invite Code: [{invite_code}] | Rank: [{rank}]")
        return await update_points_invites(self.wallet.private_key, total_points, invite_code, rank)

    async def onchain_faucet(self):
        pass

    async def push_social_tasks(self):
        return await self.portal.grab_points_social()

    @controller_log('Bound Wallet Address')
    async def bound_eoa_address(self):
        await self.portal.get_user_info()
        return await self.portal.bound_eoa_address()

    @controller_log('Bind Twitter')
    async def bind_twitter(self):
        auth_url = await self.portal.get_twitter_link()

        try:
            callback = await self.twitter.connect_twitter_to_site_oauth2(twitter_auth_url=auth_url)
            await self.twitter.close()

            bind_twitter = await self.portal.bind_twitter(callback=callback)

            if bind_twitter.get('data') == 'ok':
                return 'Success Bind Twitter'

            raise Exception(f"Failed | {bind_twitter.get('error')}")

        except Exception as e:
            logger.error(e)

        finally:
            await self.twitter.close()

    @controller_log('Twitter Tasks')
    async def twitter_tasks(self, twitter_tasks: list):
        results = []

        try:
            await self.twitter.initialize()

            for task in twitter_tasks:
                await asyncio.sleep(random.randint(5,10))

                if task['action_type_name'] == 'FOLLOW KITE AI':
                    name = task['action_type_name']
                    result = await self.twitter.follow_account(account_name="GoKiteAI")
                    if result:
                        results.append(f"Success | {result} |{name}")

                if task['action_type_name'] == 'FOLLOW KITE FRENS ECO':
                    name = task['action_type_name']
                    result = await self.twitter.follow_account(account_name="Kite_Frens_Eco")
                    if result:
                        results.append(f"Success | {result} |{name}")

                if "Retweet Kite AI's post" in task['action_type_name']:
                        name = task['action_type_name']
                        result = await self.twitter.retweet(tweet_id=1969275764349497365)

                        if result:
                            results.append(f"Success | {result} | {name}")

            return results

        except Exception as e:
            logger.error(e)
            return f'Failed | {e}'

        finally:
            await self.twitter.close()

    async def discord_tasks(self):
        pass

    async def onboard_to_portal(self, onchain_faucet: False):
        now = datetime.now()
        result = None
        user_info = await self.portal.get_user_info()

        if not user_info['onboarding_quiz_completed']:
            result = await self.portal.onboard_flow()
            if 'Failed' not in result:
                logger.success(result)

        if onchain_faucet:
            if self.wallet.next_faucet_time <= now:
                result = await self.portal.on_chain_faucet()

                if 'Failed' not in result:
                    logger.success(result)

                else:
                    logger.warning(result)

        else:
            if user_info['faucet_claimable']:
                result = await self.portal.faucet()

                if 'Failed' not in result:
                    logger.success(result)
                    await asyncio.sleep(15, 10)
                    portal_balance = await self.portal.get_balances()
                    if portal_balance > 0.01:
                        result = await self.portal.withdrawal_from_portal(amount=1)

                    else: return await self.onboard_to_portal(onchain_faucet=True)

        if not result:
            return 'Skipping Onboard'

        return 'Onboard Completed'


    async def build_actions(self):

        settings = Settings()

        actions = []

        build_actions = []

        end_actions = []

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
                    balance = await self.client.wallet.balance()

                else:
                    raise Exception(f"Controller | {onboard}")

            except Exception as e:
                raise RuntimeError(f"{e} ")

        user_info = await self.portal.get_user_info()

        if user_info['faucet_claimable']:
            #todo think about faucet atm
            build_actions.append(lambda: self.portal.faucet())

        if not user_info['onboarding_quiz_completed']:
            actions.append(lambda: self.portal.onboard_flow())

        if self.wallet.twitter_token:
            if self.wallet.twitter_status in [TwitterStatuses.ok, None]:
                if user_info.get('social_accounts').get('twitter').get('id') == "":
                        actions.append(lambda: self.bind_twitter())
                else:
                    twitter_tasks = await self.portal.get_twitter_tasks(user_data=user_info)
                    if twitter_tasks:
                        build_actions.append(lambda: self.twitter_tasks(twitter_tasks=twitter_tasks))

        if not user_info['daily_quiz_completed']:
            build_actions.append(lambda: self.portal.daily_quest_flow())

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

        if self.wallet.next_ai_conversation_time is None or self.wallet.next_ai_conversation_time <= now:
            build_actions += [lambda: self.portal.ai_agent_chat_flow() for _ in range(ai_dialogs_count)]

        ### ONCHAIN BLOCK ####
        if float(balance.Ether) > 0:
            build_actions += [lambda: self.onchain.controller(action='swap') for _ in range(swaps_count)]

            if not await self.onchain.check_bridge_status():
                build_actions.append(lambda: self.onchain.controller(action='bridge'))

            multisig_wallets = await self.safe.get_safe_addresses()

            if 'Failed' not in multisig_wallets:

                if not multisig_wallets:
                    build_actions += [lambda: self.safe.create_account() for _ in range(2)]

                else:
                    if self.wallet.next_faucet_time <= now:
                        build_actions += [lambda: self.safe.create_account() for _ in range(2)]
                        build_actions += [lambda: self.safe.send_native_to_multisig(
                            random.choice(multisig_wallets)
                        ) for _ in range(random.randint(2, 3))]

                        end_actions += [lambda: self.safe.send_native_from_safe(
                        ) for _ in range(random.randint(1, 2))]

        staking_amounts = await self.portal.get_stake_amounts()

        if staking_amounts <= 2:
            portal_balance = await self.portal.get_balances()

            if portal_balance > 1.01:
                build_actions.append(lambda: self.portal.stake(amount=1))

            chance_to_claim_stake_rewards = random.randint(1, 10)
            if chance_to_claim_stake_rewards == 5:
                staked_amounts = await self.portal.check_staked_balance()

                if len(staked_amounts) > 0:
                    agent = staked_amounts
                    build_actions.append(lambda: self.portal.claim_staking_rewards(agent=agent))

        build_actions.append(lambda: self.portal.grab_points_social())
        # portal_balance = await self.portal.get_balances()
        #
        # if portal_balance.get('kite') > 0.01:
        #     build_actions.append(lambda: self.portal.withdrawal_from_portal(amount=1))

        random.shuffle(build_actions)

        actions += build_actions
        actions += end_actions

        return actions

    @controller_log('Bind Discord')
    async def bind_discord(self):
        guild_id = '1298000367283601428'

        u = await self.portal.get_user_info()

        if u.get('social_accounts').get('discord').get('id') == '':

            try:
                discord = DiscordOAuth(wallet=self.wallet, guild_id=guild_id)

                discord_link = await self.portal.get_discord_link()

                await asyncio.sleep(random.randint(1, 3))

                oauth_url, state = await discord.start_oauth2(oauth_url=discord_link)

                bind  = await self.portal.bind_discord(callback=oauth_url)

                if bind.get('data'):
                    logger.debug(bind)
                    self.wallet.discord_status = DiscordStatus.ok

                    return f'Discord Successfully binded'

                return f'Failed to bind | {bind}'

            except Exception as e:
                if 'You need to verify your account in order to perform':
                    self.wallet.discord_status = DiscordStatus.verify
                    db.commit()

                    raise e

        else:
            return f"Already binded discord {u.get('social_accounts').get('discord').get('username')}"

    @controller_log('Join GoKiteAi Discord Channel')
    async def join_discord_channel(self):

        if self.wallet.discord_status in [None, DiscordStatus.joined]:
            bind = await self.bind_discord()
            if 'Failed' not in bind:
                logger.success(bind)

        if self.wallet.discord_status in [None, DiscordStatus.ok]:

            guild_id = '1298000367283601428'

            try:

                discord_inviter = DiscordInviter(
                    wallet=self.wallet,
                    invite_code='gokiteai',
                    channel_id=guild_id)

                join_to_channel = await discord_inviter.start_accept_discord_invite()

                if 'Failed' not in join_to_channel:
                    self.wallet.discord_status = DiscordStatus.joined
                    db.commit()
                    return 'Success joined GoKiteAI Channel'

                else:
                    return f'Join Failed | {join_to_channel}'

            except Exception as e:
                return f"Failed | {e}"

        else: raise Exception(f'Failed | Bad discord token | {self.wallet.discord_status}')
