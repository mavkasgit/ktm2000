"""Реестр исключений разбора ОСВ 1С (#464).

Решение человека «эта строка не наша» записывается один раз и дальше
переживает повторные импорты: предпросмотр показывает такую строку статусом
``skipped``, а не ошибкой, и счётчик ошибок растёт только на действительно
неразобранных строках.

Связи с ``products`` нет намеренно. ``no_catalog`` — это именно отсутствие
артикула, а ``not_mes``/``purchased`` — чужой домен или покупное изделие.
Поэтому каталог всегда главнее: матч идёт по коду, артикулу в наименовании и
точному имени, а реестр читается только для строк, которые каталог не нашёл.
Появившийся позже артикул автоматически выигрывает у реестра, и запись можно
удалить.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Identity,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

SKIP_REASON_NOT_MES = "not_mes"
SKIP_REASON_PURCHASED = "purchased"
SKIP_REASON_NO_CATALOG = "no_catalog"

SKIP_REASONS: tuple[str, ...] = (
    SKIP_REASON_NOT_MES,
    SKIP_REASON_PURCHASED,
    SKIP_REASON_NO_CATALOG,
)

# Подписи причин — один источник для счётчика, колонки предпросмотра и
# подсказки в строке: второй словарь на фронте разъехался бы с сервером.
SKIP_REASON_LABELS: dict[str, str] = {
    SKIP_REASON_NOT_MES: "не наша номенклатура (химия, плёнки, крепёж, СИЗ, газы)",
    SKIP_REASON_PURCHASED: "покупное изделие",
    SKIP_REASON_NO_CATALOG: "нет в каталоге",
}


class Product1CSkipped(Base):
    """Разобранная строка ОСВ, которая не является ошибкой импорта.

    Уникальность — по коду номенклатуры 1С и по нормализованному
    наименованию. ``UNIQUE`` на nullable-колонке в PostgreSQL пропускает
    несколько ``NULL``, поэтому «код уникален, если задан» выполняется без
    частичного индекса. ``name_norm`` обязан быть в той же форме, что
    ``_norm_cell`` импорта (lower, NBSP → пробел, схлопывание пробелов) —
    иначе одна и та же строка 1С не найдётся в реестре на ровном месте.

    ``reason`` — закрытый словарь из трёх причин; ``decided_at``/``decided_by``
    фиксируют решение (у сида — «каталог #461»), ``note`` — свободная пометка.
    """

    __tablename__ = "product_1c_skipped"
    __table_args__ = (
        CheckConstraint(
            "code IS NOT NULL OR name_norm IS NOT NULL",
            name="ck_product_1c_skipped_identity",
        ),
        CheckConstraint(
            "reason IN ('not_mes', 'purchased', 'no_catalog')",
            name="ck_product_1c_skipped_reason",
        ),
        UniqueConstraint("code", name="uq_product_1c_skipped_code"),
        UniqueConstraint("name_norm", name="uq_product_1c_skipped_name_norm"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True
    )
    code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name_norm: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reason: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
