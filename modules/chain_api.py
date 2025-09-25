import random

from libs.base import Base
from libs.eth_async.client import Client
from utils.browser import Browser
from utils.db_api.models import Wallet


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
        if data.get("items"):
            items = data.get("items")
            return items
            tx = random.choice(items)

            return tx.get("hash")
