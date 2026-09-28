"""Ключи ручных норм подвеса приводятся к нормальной длине артикула (#218).

Ключ нормы — **нормальная** длина из реестра артикула (ADR-0028 п. 2), а в
legacy-данных он лежит под сырьевой: ``2750`` при ``length_mm=2700``. Такой
ключ не применим ни к одной длине, поэтому резолвер на плане отдаёт пустую
ячейку, а ``PATCH`` карточки артикула с ним отклоняется (ADR-0047 п. 3,
#217). Миграция устраняет разрыв у всех артикулов с ним — не только у
``manual``, но и у ``auto``: в авто-режиме словарь не читается, поэтому тот же
разрыв там невидим и всплыл бы при первом переключении артикула в ручной режим.

Правило «на статью», а не «2750 → 2700» массово (ADR-0047 п. 1). Для каждого
числового ключа словаря норм одного артикула:

- ключ есть в реестре среди **нормальных** длин → не трогаем (у восьми
  артикулов из пар 2750 — нормальная длина, миграция 058 требует именно её);
- ключ равен **сырьевой** длине этого артикула → переписываем на
  ``length_mm`` этой же строки реестра;
- не совпал ни с чем, сырьевая длина неоднозначна (несколько нормальных
  длин с одним сырьём) или целевой ключ уже занят другой записью → сохраняем
  как есть и пишем в отчёт как требующий решения оператора. Автоматически
  подставлять длину в этих случаях нельзя: это бизнес-решение.

Не трогаем: листы (``dimension_state`` ``area``/``volume``) — у них длина одна
по определению, запись по длине одна, и подхват единственной записи при смене
полотна — разрешённый фолбэк (ADR-0047 п. 4, #126); legacy bare-словари
``{auto, manual}`` без числового ключа — они не per-length, и разворачивает их
миграция 032.

Отчёт миграции — таблица ``hanger_norm_key_migration``: по строке на ключ,
``status='rewritten'`` с новым ключом либо ``status='unresolved'`` с причиной.
Без неё и повторный прогон, и downgrade не знали бы, что именно менялось.

Идемпотентна: после первого прохода переписанный ключ сам стал нормальной
длиной, а отчёт защищён ``UNIQUE (product_id, old_key)`` — повторный прогон не
добавляет ни строки данных, ни строки отчёта.

Irreversible: no — downgrade возвращает ключи, записанные в отчёт, и убирает
таблицу отчёта.
"""
from typing import Sequence, Union

import json

import sqlalchemy as sa
from alembic import op


revision: str = "067_hanger_norm_key_normalization"
down_revision: Union[str, None] = "066_route_signature_backfill"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

REPORT_TABLE = "hanger_norm_key_migration"

STATUS_REWRITTEN = "rewritten"
STATUS_UNRESOLVED = "unresolved"

REASON_NOT_IN_REGISTRY = "not_in_registry"
REASON_AMBIGUOUS_RAW = "ambiguous_raw_length"
REASON_TARGET_TAKEN = "target_key_exists"

_WRITE_NORMS_SQL = (
    "UPDATE products SET attributes = jsonb_set("
    "attributes, '{quantity_per_hanger}', CAST(:norms AS jsonb)) WHERE id = :product_id"
)


def _length_key(length_mm: float) -> str:
    """Канонический ключ длины в мм (зеркало ``app.models.product._length_key``).

    Продублировано, а не импортировано: миграция — снимок на момент
    применения и не должна ломаться о последующие правки модели.
    """
    value = float(length_mm)
    return str(int(value)) if value.is_integer() else str(value)


def _parse_key(key: str) -> float | None:
    """Числовой ключ словаря норм либо None для нечислового (legacy bare)."""
    try:
        return float(key)
    except (TypeError, ValueError):
        return None


def _report_table_exists(bind) -> bool:
    return REPORT_TABLE in set(sa.inspect(bind).get_table_names())


def _create_report_table() -> None:
    op.create_table(
        REPORT_TABLE,
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("sku", sa.String(length=100), nullable=False),
        sa.Column("old_key", sa.String(length=32), nullable=False),
        sa.Column("new_key", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{REPORT_TABLE}")),
        sa.UniqueConstraint(
            "product_id", "old_key", name=op.f(f"uq_{REPORT_TABLE}_product_old_key")
        ),
        sa.CheckConstraint(
            f"status IN ('{STATUS_REWRITTEN}', '{STATUS_UNRESOLVED}')",
            name=op.f(f"ck_{REPORT_TABLE}_status"),
        ),
    )


def _load_products(bind) -> list:
    """Линейные артикулы, у которых словарь норм — per-length объект."""
    return list(
        bind.execute(
            sa.text(
                "SELECT p.id AS product_id, p.sku, "
                "p.attributes->'quantity_per_hanger' AS norms "
                "FROM products p "
                "WHERE p.dimension_state = 'length' "
                "  AND jsonb_typeof(p.attributes->'quantity_per_hanger') = 'object'"
            )
        ).mappings()
    )


def _load_registry(bind, product_id: int) -> tuple[set, dict]:
    """(нормальные длины артикула, сырьевая длина → нормальные длины)."""
    normal: set = set()
    raw: dict = {}
    for row in bind.execute(
        sa.text(
            "SELECT length_mm, raw_length_mm FROM product_lengths WHERE product_id = :product_id"
        ),
        {"product_id": product_id},
    ).mappings():
        length = float(row["length_mm"])
        normal.add(length)
        if row["raw_length_mm"] is not None:
            raw.setdefault(float(row["raw_length_mm"]), set()).add(length)
    return normal, raw


def _plan(norms: dict, normal: set, raw: dict) -> tuple[dict, list]:
    """(новый словарь норм, строки отчёта (old_key, new_key, reason))."""
    planned = dict(norms)
    report: list = []
    for key in list(norms):
        value = _parse_key(key)
        # Нечисловой ключ (legacy bare) и ключ, уже совпадающий с нормальной
        # длиной артикула, — не наш случай (см. докстринг миграции).
        if value is None or value in normal:
            continue

        targets = raw.get(value, set())
        if not targets:
            report.append((key, None, REASON_NOT_IN_REGISTRY))
            continue
        if len(targets) > 1:
            report.append((key, None, REASON_AMBIGUOUS_RAW))
            continue

        new_key = _length_key(next(iter(targets)))
        # Целевой ключ уже занят — другой записью в словаре или ключом,
        # перенесённым выше в этом же проходе (legacy-ключи «2750» и «2750.0»
        # дают один канонический ключ). Перезапись стёрла бы ручной ввод.
        if new_key in planned:
            report.append((key, None, REASON_TARGET_TAKEN))
            continue

        planned[new_key] = norms[key]
        del planned[key]
        report.append((key, new_key, None))
    return planned, report


def _write_norms(bind, product_id: int, norms: dict) -> None:
    """Записать словарь норм артикула целиком (миграция меняет только его)."""
    bind.execute(
        sa.text(_WRITE_NORMS_SQL),
        {"product_id": product_id, "norms": json.dumps(norms)},
    )


def _insert_report_row(bind, product: dict, old_key: str, new_key, reason) -> None:
    """Записать строку отчёта (идемпотентно — по product_id + old_key)."""
    bind.execute(
        sa.text(
            f"INSERT INTO {REPORT_TABLE} "
            "(product_id, sku, old_key, new_key, status, reason) "
            "VALUES (:product_id, :sku, :old_key, :new_key, :status, :reason) "
            "ON CONFLICT (product_id, old_key) DO NOTHING"
        ),
        {
            "product_id": product["product_id"],
            "sku": product["sku"],
            "old_key": old_key,
            "new_key": new_key,
            "status": STATUS_REWRITTEN if new_key is not None else STATUS_UNRESOLVED,
            "reason": reason,
        },
    )


def upgrade() -> None:
    bind = op.get_bind()
    # Отчёт — накопительный артефакт: повторный прогон (например, после
    # ``alembic stamp`` к предыдущей ревизии при ручной переигровке) не должен
    # уничтожать уже записанные строки, поэтому таблица создаётся, если её нет.
    if not _report_table_exists(bind):
        _create_report_table()

    for product in _load_products(bind):
        norms = product["norms"] or {}
        normal, raw = _load_registry(bind, product["product_id"])
        planned, report = _plan(norms, normal, raw)
        if planned != norms:
            _write_norms(bind, product["product_id"], planned)
        for old_key, new_key, reason in report:
            _insert_report_row(bind, product, old_key, new_key, reason)


def downgrade() -> None:
    bind = op.get_bind()
    if not _report_table_exists(bind):
        return

    changes_by_product: dict = {}
    for row in bind.execute(
        sa.text(
            f"SELECT product_id, old_key, new_key FROM {REPORT_TABLE} "
            f"WHERE status = '{STATUS_REWRITTEN}' ORDER BY product_id, old_key"
        )
    ).mappings():
        changes_by_product.setdefault(row["product_id"], []).append(dict(row))

    for product_id, changes in changes_by_product.items():
        current = bind.execute(
            sa.text(
                "SELECT attributes->'quantity_per_hanger' AS norms FROM products WHERE id = :id"
            ),
            {"id": product_id},
        ).mappings().first()
        if current is None:
            continue
        norms = current["norms"] or {}
        for change in changes:
            # Ключ могли переписать уже после миграции — тогда откатывать нечего.
            if change["new_key"] not in norms or change["old_key"] in norms:
                continue
            norms[change["old_key"]] = norms.pop(change["new_key"])
        _write_norms(bind, product_id, norms)

    op.drop_table(REPORT_TABLE)
