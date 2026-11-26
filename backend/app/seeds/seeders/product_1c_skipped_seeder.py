"""Сид реестра исключений разбора ОСВ 1С (#464).

Идемпотентность: сид только **добавляет** недостающие записи. Существующую
строку он не перезаписывает — решение человека (``reason``/``note``) главнее
сида, а повторные запуски ``db:seed`` не должны откатывать правки и не должны
плодить дубли. Ключ поиска — код номенклатуры 1С, затем ``name_norm``: в
данных сида есть только коды, но реестр допускает запись без кода, и такой
случай тоже не должен задвоиться.

Нормализация имени — ``_norm_cell`` из импорта ОСВ, а не вторая копия правила:
иначе одна и та же строка 1С искалась бы в реестре только при совпадении
пробелов, NBSP и регистра.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product_1c_skipped import (
    SKIP_REASON_LABELS,
    SKIP_REASON_NO_CATALOG,
    SKIP_REASON_NOT_MES,
    SKIP_REASON_PURCHASED,
    Product1CSkipped,
)
from app.seeds.product_1c_skipped import PRODUCT_1C_SKIPPED
from app.stock.import_1c_osv import _norm_cell

# Откуда решение и что оно значит — в ``note``, чтобы в БД было видно
# основание, а не только код причины. Номера задач сюда не попадают: эта
# строка печатается оператору в предпросмотре импорта, а основание и история
# решения живут в документации (спека импорта ОСВ, решения приёмки).
_SEED_NOTE_BY_REASON: dict[str, str] = {
    SKIP_REASON_NOT_MES: "Не MES: химия, плёнки, крепёж, СИЗ, газы",
    SKIP_REASON_PURCHASED: "Покупное изделие, не сырьё MES",
    SKIP_REASON_NO_CATALOG: "Нет в каталоге, новые артикулы не заводим",
}
_SEED_DECIDED_BY = "каталог"


def _seed_note(reason: str) -> str:
    return _SEED_NOTE_BY_REASON.get(reason, SKIP_REASON_LABELS.get(reason, reason))


async def seed_product_1c_skipped(db: AsyncSession) -> dict[str, int]:
    """Добавить недостающие записи реестра; вернуть счётчики created/existing."""
    existing = list((await db.scalars(select(Product1CSkipped))).all())
    by_code = {row.code: row for row in existing if row.code}
    by_name = {row.name_norm: row for row in existing if row.name_norm}

    created = existing_count = 0
    for code, name, reason in PRODUCT_1C_SKIPPED:
        name_norm = _norm_cell(name)
        if code in by_code or name_norm in by_name:
            existing_count += 1
            continue
        row = Product1CSkipped(
            code=code or None,
            name_norm=name_norm,
            reason=reason,
            note=_seed_note(reason),
            decided_by=_SEED_DECIDED_BY,
        )
        db.add(row)
        if code:
            by_code[code] = row
        by_name[name_norm] = row
        created += 1

    await db.flush()
    return {"created": created, "existing": existing_count}
