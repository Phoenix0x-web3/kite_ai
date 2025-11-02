import asyncio
import random
from typing import Optional

from faker import Faker
from loguru import logger
from patchright.async_api import async_playwright
from patchright.sync_api import Frame

from data.settings import Settings
from utils import selectors
from utils.browser import Browser
from utils.db_api.models import Wallet
from utils.discord.discord import DiscordInviter
from utils.retry import async_retry
from utils.selectors import Selector
from utils.twitter.twitter_client import TwitterClient

from .base_browser.pw_browser import BrowserBase
from .js.fake_kite_builder import KiteAirdropAnswerBuilder
from .js.mouse import MouseOverlay


class PwForm:
    def __init__(
        self,
        wallet: Wallet,
    ):
        self.wallet = wallet
        self.proxy = self.wallet.proxy
        self.page = None
        self.capmonster_api_key = Settings().capmonster_api_key
        self.mouse = None
        self.browser = Browser(wallet=wallet)
        self.faker = Faker()

    @async_retry()
    async def handle_form(self):
        logger.info(f"{self.wallet} start Fill Form")
        browser = BrowserBase(wallet=self.wallet)
        async with async_playwright() as pw:
            await browser.open_with_fingerprint(
                pw=pw,
                grant_origins=["https://kiteai.typeform.com/AirdropAppeal"],
                headless=not Settings().show_browser,
            )

            self.page = browser.page
            await self.page.goto("https://kiteai.typeform.com/AirdropAppeal", wait_until="networkidle")
            await self.wait_and_click(selector=selectors.START)
            await self.wait_and_click(selector=selectors.YES)
            twitter_username = self.faker.user_name()
            if self.wallet.twitter_token:
                try:
                    twitter_client = TwitterClient(user=self.wallet)
                    await twitter_client.initialize()
                    twitter_username = twitter_client.twitter_account.username
                except Exception:
                    logger.error(f"{self.wallet} can't get twitter username. Use Fake")
            logger.debug(f"{self.wallet} twitter username for form: {twitter_username}")
            await self.page.fill(selectors.TWITTER_INPUT.value, "@" + str(twitter_username))
            await self.wait_and_click(selector=selectors.OK_TWITTER)
            discord_name = self.faker.user_name()
            if self.wallet.discord_token:
                guild_id = "1298000367283601428"

                discord_inviter = DiscordInviter(wallet=self.wallet, invite_code="gokiteai", channel_id=guild_id)

                _, discord_name = await discord_inviter.get_username()
                if not discord_name:
                    logger.error(f"{self.wallet} can't get discord username. Use Fake")
                    discord_name = self.faker.user_name()

            logger.debug(f"{self.wallet} discord username for form: {discord_name}")
            await self.page.fill(selectors.DISCORD_INPUT.value, str(discord_name))
            await self.wait_and_click(selector=selectors.OK_DISCORD)
            await self.page.fill(selectors.ADDRESS_INPUT.value, str(self.wallet.address))
            await self.wait_and_click(selector=selectors.OK_ADDRESS)
            builder = KiteAirdropAnswerBuilder()
            text = builder.build_single()
            logger.debug(f"{self.wallet} text for appeal: {text}")
            await self.page.fill(selectors.DESCRIPTION_INPUT.value, text)
            await self.wait_and_click(selector=selectors.SUMBIT_FORM)
            if "Thank you for your patience" in await self.page.content():
                self.wallet.fill_form = True
                return "Success fill form"
            else:
                return "Failed fill form"

    async def _ensure_mouse(self):
        if not self.mouse:
            self.mouse = MouseOverlay(self.page)
            await self.mouse.install()
            await self.mouse.start_idle()

    async def wait_and_click(
        self,
        selector: Selector | None = None,
        button_name: str | None = None,
        timeout: int = 30_000,
        retries: int = 5,
        use_js_fallback: bool = True,
        frame: Optional[Frame] = None,
    ):
        if not self.page:
            raise RuntimeError("Page is not initialized")

        await self._ensure_mouse()

        target = frame or self.page

        last_err = None
        loc = None
        if selector:
            loc = target.locator(selector.value).first
        elif button_name:
            loc = target.get_by_role("button", name=button_name)
            selector = Selector(name=button_name, value=button_name)
        if not loc or not selector:
            raise ValueError("You must provide either selector or button_name")

        await asyncio.sleep(0.3 + random.random() * 0.5)

        for attempt in range(retries + 1):
            try:
                await loc.wait_for(state="visible", timeout=min(5000, timeout))
                await self.mouse.move_and_click(loc)
                logger.debug(f"{self.wallet} | [click:ok] {selector.name}")
                await asyncio.sleep(random.randint(1, 2))
                return

            except Exception as e:
                last_err = e
                if "Page.evaluate: Execution context was destroyed, most likely because of a navigation" in str(e):
                    logger.debug(f"{self.wallet} | [click:ok] {selector.name}")
                    return
                logger.debug(f"{self.wallet} | [click:retry {attempt}/{retries}] {selector.name} -> {e}")
                await asyncio.sleep(0.3 + random.random() * 0.5)
                continue

        if use_js_fallback:
            try:
                await loc.wait_for(state="visible", timeout=min(5000, timeout))
                await self.mouse.move_and_click(loc, js=True)
                logger.debug(f"[click:fallback-js] {selector.name}")
                return
            except Exception as e:
                last_err = e

        logger.error(f"[click:fail] {selector.name} -> {last_err}")
        raise last_err or RuntimeError(f"Failed to click {selector.name}")
