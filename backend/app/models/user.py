import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Identity, Index, String, text, Table, Column
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
    __table_args__ = (
        # Partial unique: at most one active user per Authentik sub (OIDC link key).
        # Mirrors migration 013_users_authentik_sub — code does scalar() lookups by sub.
        Index(
            "ix_users_authentik_sub_active",
            "authentik_sub",
            unique=True,
            postgresql_where=text("is_active = true AND authentik_sub IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True, autoincrement=True
    )
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"), nullable=False)
    section_id: Mapped[int | None] = mapped_column(ForeignKey("sections.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default=text("true"))
    tab_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    position: Mapped[str | None] = mapped_column(String(255), nullable=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # OIDC subject from Authentik (stable link; primary match key)
    authentik_sub: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    # Multiavatar seed — cache of Authentik attributes.profile_avatar_seed
    avatar_seed: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Unified profile cache (SoT = Authentik attributes)
    locale: Mapped[str | None] = mapped_column(String(16), nullable=True)  # ru | en
    theme: Mapped[str | None] = mapped_column(String(16), nullable=True)  # system | light | dark
    profile_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    profile_sync_failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    section = relationship("Section", back_populates="legacy_users")
    sections = relationship("Section", secondary=user_sections, back_populates="users", lazy="selectin")

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
