from libs.eth_async.classes import Singleton
from libs.eth_async.data.models import RawContract, DefaultABIs


class Contracts(Singleton):

    ETH = RawContract(
        title='ETH',
        address='0x0000000000000000000000000000000000000000',
        abi=DefaultABIs.Token
    )
