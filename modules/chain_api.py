import random

from fake_useragent import UserAgent

from libs.base import Base
from libs.eth_async.client import Client
from libs.eth_async.data.models import TokenAmount
from libs.eth_async.utils.web_requests import async_get ,request_params
from utils.browser import Browser

from utils.db_api.models import Wallet
from utils.db_api.wallet_api import db


class BlockScout(Base):
    def __init__(self, client: Client, wallet: Wallet):
        self.client = client
        self.wallet = wallet
        self.session = Browser(wallet=wallet)
        self.url = f"{self.client.network.explorer}"

    async def get_random_tx(self):
        url = f"{self.client.network.explorer}/api/v2/transactions?filter=validated"
        r = await self.session.get(url=url)

        data = r.json()
        if data.get('items'):
            items = data.get('items')
            tx = random.choice(items)

            return tx.get('hash')

