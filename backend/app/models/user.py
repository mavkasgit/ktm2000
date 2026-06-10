import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Identity, String, text, Table, Column
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class UserRole(str, enum.Enum):
    admin = "admin"
    planner = "planner"
    section_manager = "section_manager"
    operator = "operator"
    viewer = "viewer"
    transporter = "transporter"


user_sections = Table(
    "user_sections",
    Base.metadata,
    Column("user_id", BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("section_id", BigInteger, ForeignKey("sections.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True, autoincrement=True
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"), nullable=False)
    section_id: Mapped[int | None] = mapped_column(ForeignKey("sections.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    section = relationship("Section", back_populates="legacy_users")
    sections = relationship("Section", secondary=user_sections, back_populates="users", lazy="selectin")
    login_tokens = relationship("UserLoginToken", back_populates="user", lazy="selectin", cascade="all, delete-orphan")

    @property
    def active_login_token(self):
        from datetime import datetime, timezone
        now_time = datetime.now(timezone.utc)
        for t in self.login_tokens:
            if not t.is_used and t.expires_at > now_time:
                return t
        return None

    @property
    def section_ids(self) -> list[int]:
        return [s.id for s in self.sections]


from sqlalchemy import event

@event.listens_for(User, 'before_insert')
def set_default_username(mapper, connection, target: User):
    if not target.username:
        if target.email:
            target.username = target.email.split("@")[0]
        else:
            target.username = "user"
