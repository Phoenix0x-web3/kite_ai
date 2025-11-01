from datetime import datetime

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from data.constants import PROJECT_SHORT_NAME
from data.settings import Settings


class Base(DeclarativeBase):
    pass


class Wallet(Base):
    __tablename__ = "wallets"

    id: Mapped[int] = mapped_column(primary_key=True)
    private_key: Mapped[str] = mapped_column(unique=True, index=True)
    address: Mapped[str] = mapped_column(unique=True)
    proxy: Mapped[str] = mapped_column(default=None, nullable=True)
    eoa_address: Mapped[str] = mapped_column(default=None, nullable=True)
    # next_activity_action_time: Mapped[datetime | None] = mapped_column(default=None, nullable=True)
    points: Mapped[int] = mapped_column(default=0)
    rank: Mapped[int] = mapped_column(default=0)
    invite_code: Mapped[str] = mapped_column(default="")
    bound_eoa_address: Mapped[str] = mapped_column(default="")
    twitter_token: Mapped[str] = mapped_column(default=None, nullable=True)
    twitter_status: Mapped[str] = mapped_column(default=None, nullable=True)
    discord_token: Mapped[str] = mapped_column(default=None, nullable=True)
    discord_proxy: Mapped[str] = mapped_column(default=None, nullable=True)
    discord_status: Mapped[str] = mapped_column(default=None, nullable=True)
    next_faucet_time: Mapped[datetime] = mapped_column(default=datetime.now)
    next_ai_conversation_time: Mapped[datetime] = mapped_column(default=datetime.now)
    auth_token: Mapped[str] = mapped_column(default=None, nullable=True)
    completed: Mapped[bool] = mapped_column(default=False)

    def __repr__(self):
        if Settings().show_wallet_address_logs:
            return f"[{PROJECT_SHORT_NAME} | {self.id} | {self.address}]"
        return f"[{PROJECT_SHORT_NAME} | {self.id}]"
