import asyncio
import os
import random
from datetime import datetime, timedelta
from typing import List

from loguru import logger

from data.config import FILES_DIR
from data.settings import Settings
from functions.controller import Controller
from libs.eth_async.client import Client
from libs.eth_async.data.models import Networks
from utils.db_api.models import Wallet
from utils.db_api.wallet_api import db
from utils.db_import_export_sync import parse_proxy, pick_proxy, read_lines, remove_line_from_file
from utils.discord.discord import DiscordStatus
from utils.encryption import check_encrypt_param


async def random_sleep_before_start(wallet):
    random_sleep = random.randint(Settings().random_pause_start_wallet_min, Settings().random_pause_start_wallet_max)
    now = datetime.now()

    logger.info(f"{wallet} Start at {now + timedelta(seconds=random_sleep)} sleep {random_sleep} seconds before start actions")
    await asyncio.sleep(random_sleep)


async def random_activity_task(wallet):
    try:
        await random_sleep_before_start(wallet=wallet)

        client = Client(private_key=wallet.private_key, network=Networks.KiteTestnet, proxy=wallet.proxy)
        controller = Controller(client=client, wallet=wallet)

        actions = await controller.build_actions()

        if isinstance(actions, str):
            logger.warning(actions)

        else:
            logger.info(f"{wallet} | Started Activity Tasks | Wallet will do {len(actions)} actions")

            for action in actions:
                sleep = random.randint(Settings().random_pause_between_actions_min, Settings().random_pause_between_actions_max)
                try:
                    status = await action()

                    if "AI Agent rate limit" in status:
                        logger.warning(status)

                    elif "Failed" not in status:
                        logger.success(status)
                    else:
                        logger.error(status)

                except RuntimeError as e:
                    logger.error(e)

                except Exception as e:
                    if "Failed to perform, curl" in str(e):
                        proxies = read_lines("reserve_proxy.txt")

                        proxy = parse_proxy(pick_proxy(proxies, 0))
                        wallet.proxy = proxy
                        db.commit()
                        remove_line_from_file(proxy, "reserve_proxy.txt")
                        return await random_activity_task(wallet)
                    logger.error(e)
                    continue

                finally:
                    await asyncio.sleep(sleep)

        await controller.update_db_by_user_info()

    except asyncio.CancelledError:
        raise

    except Exception as e:
        logger.error(f"Core | Activity | {e} | {wallet}")
        raise e


async def join_discord(wallet):
    client = Client(private_key=wallet.private_key, proxy=wallet.proxy, network=Networks.KiteTestnet)

    controller = Controller(client=client, wallet=wallet)

    try:
        result = await controller.join_discord_channel()
        await controller.push_social_tasks()
        if "Failed" not in result:
            logger.success(result)

            return result

        logger.error(result)

    except Exception as e:
        if "Failed to perform, curl" in str(e):
            proxies = read_lines("reserve_proxy.txt")

            proxy = parse_proxy(pick_proxy(proxies, 0))
            wallet.proxy = proxy
            db.commit()
            remove_line_from_file(proxy, "reserve_proxy.txt")
            return await join_discord(wallet)
            logger.error(e)


async def push_social_tasks(wallet):
    await random_sleep_before_start(wallet=wallet)
    client = Client(private_key=wallet.private_key, proxy=wallet.proxy, network=Networks.KiteTestnet)

    controller = Controller(client=client, wallet=wallet)

    try:
        result = await controller.push_social_tasks()

        if "Failed" not in result:
            logger.success(result)

            return result

        logger.error(result)

    except Exception as e:
        if "Failed to perform, curl" in str(e):
            proxies = read_lines("reserve_proxy.txt")

            proxy = parse_proxy(pick_proxy(proxies, 0))
            wallet.proxy = proxy
            db.commit()
            remove_line_from_file(proxy, "reserve_proxy.txt")
            return await push_social_tasks(wallet)
        logger.error(e)


async def bound_eoa(wallet):
    await random_sleep_before_start(wallet=wallet)
    client = Client(private_key=wallet.private_key, proxy=wallet.proxy, network=Networks.KiteTestnet)

    controller = Controller(client=client, wallet=wallet)

    try:
        await controller.portal.get_user_info()
        current_eoa = await controller.portal.get_current_eoa()
        current_eoa = current_eoa.get("current_eoa_address")

        if current_eoa != wallet.bound_eoa_address:
            logger.warning(f"Detected not walid bound address: {current_eoa} | need: {wallet.address}")

            result = await controller.bound_eoa_address()

            if "Failed" not in result:
                logger.success(result)

                return result

        else:
            logger.info(f"Already Bounded Same: {current_eoa} <-> client_address: {wallet.bound_eoa_address}")

            return "Already Bounded Same"

        logger.error(result)

    except Exception as e:
        if "Failed to perform, curl" in str(e):
            proxies = read_lines("reserver_proxy.txt")

            proxy = parse_proxy(pick_proxy(proxies, 0))

            wallet.proxy = proxy
            print(wallet.proxy)
            db.commit()
            return await bound_eoa(wallet)
            logger.error(e)


async def execute(wallets: List[Wallet], task_func, random_pause_wallet_after_completion: int = 0):
    while True:
        semaphore = asyncio.Semaphore(min(len(wallets), Settings().threads))

        if Settings().shuffle_wallets:
            random.shuffle(wallets)

        async def sem_task(wallet: Wallet):
            async with semaphore:
                try:
                    await asyncio.wait_for(task_func(wallet), timeout=3600)

                except asyncio.TimeoutError:
                    logger.error(f"[{wallet.id}] | Core Execution Tasks |{task_func.__name__} timed out after 60m")

                except Exception as e:
                    logger.error(f"[{wallet.id}] failed: {e}")

        tasks = [asyncio.create_task(sem_task(wallet)) for wallet in wallets]
        await asyncio.gather(*tasks, return_exceptions=True)

        if random_pause_wallet_after_completion == 0:
            break

        # update dynamically the pause time
        random_pause_wallet_after_completion = random.randint(
            Settings().random_pause_wallet_after_completion_min, Settings().random_pause_wallet_after_completion_max
        )

        next_run = datetime.now() + timedelta(seconds=random_pause_wallet_after_completion)
        logger.info(f"Sleeping {random_pause_wallet_after_completion} seconds. Next run at: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
        await asyncio.sleep(random_pause_wallet_after_completion)


async def activity(action: int):
    if not check_encrypt_param():
        logger.error(f"Decryption Failed | Wrong Password")
        return

    wallets = db.all(Wallet)

    range_wallets = Settings().range_wallets_to_run
    if range_wallets != [0, 0]:
        start, end = range_wallets
        wallets = [wallet for i, wallet in enumerate(wallets, start=1) if start <= i <= end]
    else:
        if Settings().exact_wallets_to_run:
            wallets = [wallet for i, wallet in enumerate(wallets, start=1) if i in Settings().exact_wallets_to_run]

    if action == 1:
        await execute(
            wallets,
            random_activity_task,
            random.randint(Settings().random_pause_wallet_after_completion_min, Settings().random_pause_wallet_after_completion_max),
        )

    elif action == 2:
        wallets = [wallet for wallet in wallets if wallet.discord_token is not None and wallet.discord_status in [None, DiscordStatus.ok]]

        if len(wallets) == 0:
            logger.warning(f"Core | Founded {len(wallets)} wallets with discord tokens, import some tokens in DB. Exiting...")
            return

        if Settings().discord_proxy:
            file_path = os.path.join(FILES_DIR, "discord_proxy.txt")

            with open(file_path, "r", encoding="utf-8") as f:
                discord_proxies = f.read().splitlines()

            if len(discord_proxies) == 0:
                logger.warning("Core | No discord proxies provided, add some proxies in files/discord_proxy.txt. Exiting...")
                return

            n_proxies = len(discord_proxies)

            for i, w in enumerate(wallets):
                w.discord_proxy = discord_proxies[i % n_proxies]

        await execute(wallets, join_discord, 0)

    elif action == 3:
        await execute(wallets, push_social_tasks)

    elif action == 4:
        await execute(wallets, bound_eoa)
    #
    # elif action == 3:
    #     await execute(wallets, test_web3, random.randint(Settings().random_pause_wallet_after_completion_min, Settings().random_pause_wallet_after_completion_max))
    #
    # elif action == 4:
    #     await execute(wallets, test_twitter)
