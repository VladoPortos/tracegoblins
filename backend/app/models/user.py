import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(CITEXT, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(120))
    initials: Mapped[str | None] = mapped_column(String(4), default=None)
    avatar_color: Mapped[str | None] = mapped_column(String(16), default=None)
    role: Mapped[str] = mapped_column(String(16), default="user")  # admin|user
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    totp_secret: Mapped[str | None] = mapped_column(Text, default=None)  # Fernet ciphertext of the TOTP secret
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    totp_last_used_step: Mapped[int | None] = mapped_column(BigInteger, default=None)  # replay guard
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
