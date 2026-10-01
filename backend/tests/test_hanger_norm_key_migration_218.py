"""#218 (ADR-0047): после миграции 066 норма подвеса становится применимой.

Проверяется результат миграции на публичных швах, а не на её внутренностях:

- карточка артикула, которую до миграции блокировала норма-сирота
  (ADR-0047 п. 3, #217), после миграции сохраняется, а ручное значение не
  теряется;
- авто-режим считает то же самое, что и до миграции: словарь норм в нём не
  читается, движок работает по периметру и габариту (ADR-0047 п. 2);
- регресс листа: у ``dimension_state`` area/volume запись по длине одна, и
  фолбэк на единственную запись при смене полотна остаётся (ADR-0047 п. 4,
  #126).

Схема здесь — та, что поднял alembic до ревизии 066, а не ``create_all``:
миграция обязана работать на реальной цепочке ревизий.
"""
from __future__ import annotations

import os
import socket
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import pytest
from app.core.database import get_db
from app.main import app
from app.models.product import DimensionState, Product
from app.services.plan_position_hanger import resolve_position_hanger
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.helpers.mig_db import (
    create_migration_db,
    drop_migration_db,
    migration_db_url,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
PREV_REVISION = "066_route_signature_backfill"
HEAD_REVISION = "067_hanger_norm_key_normalization"


def _db_reachable() -> bool:
    """Тестовый Postgres доступен? DSN — у хелпера миграционных баз."""
    parsed = urlparse(migration_db_url())
    try:
        with socket.create_connection(
            (parsed.hostname or "localhost", parsed.port or 5432), timeout=2
        ):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _db_reachable(),
    reason="PostgreSQL server not reachable for migration test",
)


def _alembic(target_url: str, tmp_path: Path, *args: str) -> None:
    """Запустить alembic в подпроцессе с DSN тестовой БД (5441), не трогая dev.

    ``ENV_FILE`` указывает на несуществующий путь внутри ``tmp_path``:
    ``alembic/env.py`` по умолчанию перекрывает ``DATABASE_URL`` содержимым
    ``$ENV_FILE`` (по умолчанию ``<repo>/.env.dev``), а на отсутствующем файле
    ``apply_env_file()`` — no-op, так что DSN остаётся тем, что дал тест.
    """
    result = subprocess.run(
        ["alembic", *args],
        cwd=BACKEND_DIR,
        env={
            **os.environ,
            "DATABASE_URL": target_url,
            "ENV_FILE": str(tmp_path / "absent.env"),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


async def _seed(session_factory, *, linear_norms: dict, auto_norms: dict) -> dict:
    """Артикулы до миграции: линейный с ключом-сиротой, авто-режим и лист.

    Лист нужен именно здесь: миграция обязана пройти мимо него, не тронув
    единственную запись по длине полотна (ADR-0047 п. 4).
    """
    from app.models.dimension import DimensionType, ProductDimension

    async with session_factory() as session:
        linear = Product(
            sku="MIG218-LINEAR",
            name="Линейный",
            type="component",
            unit="pcs",
            attributes={
                "hanger_mode": "manual",
                "quantity_per_hanger": linear_norms,
            },
        )
        auto = Product(
            sku="MIG218-AUTO",
            name="Авто",
            type="component",
            unit="pcs",
            attributes={
                "hanger_mode": "auto",
                "perimeter_mm": 100,
                "mount_width_mm": 50,
                "quantity_per_hanger": auto_norms,
            },
        )
        sheet = Product(
            sku="MIG218-SHEET",
            name="Лист",
            type="component",
            unit="pcs",
            dimension_state=DimensionState.area,
            attributes={
                "hanger_mode": "manual",
                "quantity_per_hanger": {"2000": {"auto": None, "manual": 5}},
            },
        )
        session.add_all([linear, auto, sheet])
        await session.flush()
        for code in ("length_mm", "width_mm"):
            session.add(DimensionType(code=code, name=code, unit="мм", value_type="number"))
        await session.flush()
        types = dict(
            (
                await session.execute(
                    select(DimensionType.code, DimensionType.id).where(
                        DimensionType.code.in_(("length_mm", "width_mm"))
                    )
                )
            ).all()
        )
        for code, value in (("length_mm", 2000.0), ("width_mm", 500.0)):
            session.add(
                ProductDimension(
                    product_id=sheet.id,
                    dimension_type_id=types[code],
                    default_value=value,
                )
            )
        await session.execute(
            text(
                "INSERT INTO product_lengths (product_id, length_mm, raw_length_mm, is_primary) "
                "VALUES (:linear, 2700, 2750, true), (:auto, 2700, 2750, true)"
            ),
            {"linear": linear.id, "auto": auto.id},
        )
        await session.commit()
        return {"linear": linear.id, "auto": auto.id, "sheet": sheet.id}


@pytest.mark.asyncio
async def test_after_migration_card_patch_keeps_norm_and_sheet_fallback_works(tmp_path: Path):
    """Артикул с ключом-сиротой перестаёт блокировать правку; ручная N сохранена."""
    db_name, target_url = await create_migration_db()

    engine = create_async_engine(target_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    try:
        _alembic(target_url, tmp_path, "upgrade", PREV_REVISION)
        ids = await _seed(
            session_factory,
            linear_norms={"2750": {"auto": None, "manual": 62}},
            auto_norms={"2750": {"auto": 48, "manual": None}},
        )

        # До миграции у линейного артикула на плане пусто: ключ 2750 не
        # совпадает с нормальной длиной позиции 2700 (ADR-0047, инцидент).
        async with session_factory() as session:
            linear_before = resolve_position_hanger(
                await session.get(Product, ids["linear"]),
                length_mm=2700,
                payload_quantity_per_hanger=None,
            )
            auto_before = resolve_position_hanger(
                await session.get(Product, ids["auto"]),
                length_mm=2700,
                payload_quantity_per_hanger=None,
            )
        assert linear_before.quantity_per_hanger is None
        assert linear_before.source is None
        # Регресс авто-режима: словарь норм в нём не читается, движок считает
        # по периметру и габариту — до и после миграции одно и то же.
        assert auto_before.source == "auto"
        assert auto_before.quantity_per_hanger is not None

        _alembic(target_url, tmp_path, "upgrade", HEAD_REVISION)

        async with session_factory() as session:
            linear_after = resolve_position_hanger(
                await session.get(Product, ids["linear"]),
                length_mm=2700,
                payload_quantity_per_hanger=None,
            )
            auto_after = resolve_position_hanger(
                await session.get(Product, ids["auto"]),
                length_mm=2700,
                payload_quantity_per_hanger=None,
            )
        # Норма наконец применяется: та же позиция plan-level даёт число подвесов.
        assert linear_after.quantity_per_hanger == 62
        assert linear_after.source == "manual"
        assert auto_after == auto_before

        # Миграция прошла мимо листа: запись по длине одна и не переехала.
        async with session_factory() as session:
            sheet_after = await session.get(Product, ids["sheet"])
            assert sheet_after.quantity_per_hanger_by_length == {
                "2000": {"auto": None, "manual": 5}
            }

        async def override_get_db():
            async with session_factory() as session:
                yield session
                await session.commit()

        app.dependency_overrides[get_db] = override_get_db
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as ac:
                linear = await ac.get(f"/api/products/{ids['linear']}")
                assert linear.status_code == 200, linear.text
                assert linear.json()["quantity_per_hanger"] == {
                    "2700": {"auto": None, "manual": 62}
                }

                # Раньше ключ 2750 был вне реестра и правка падала с 422.
                patched = await ac.patch(
                    f"/api/products/{ids['linear']}", json={"notes": "Правка после миграции"}
                )
                assert patched.status_code == 200, patched.text
                assert patched.json()["quantity_per_hanger"] == {
                    "2700": {"auto": None, "manual": 62}
                }

                # Регресс листа: миграция прошла мимо единственной записи, и
                # смена полотна по-прежнему подхватывает её (ADR-0047 п. 4).
                sheet_id = ids["sheet"]
                async with session_factory() as session:
                    length_link = (
                        await session.execute(
                            text(
                                "SELECT pd.id FROM product_dimensions pd "
                                "JOIN dimension_types dt ON dt.id = pd.dimension_type_id "
                                "WHERE pd.product_id = :product_id AND dt.code = 'length_mm'"
                            ),
                            {"product_id": sheet_id},
                        )
                    ).scalar_one()
                resized = await ac.patch(
                    f"/api/products/{sheet_id}/dimensions/{length_link}",
                    json={"default_value": 3000.0},
                )
                assert resized.status_code == 200, resized.text
                saved = await ac.patch(
                    f"/api/products/{sheet_id}", json={"notes": "Смена полотна"}
                )
                # Ручная N переехала на новую длину полотна (auto считается
                # движком живьём — #126, поэтому его не проверяем).
                assert saved.json()["quantity_per_hanger"]["3000"]["manual"] == 5
                assert list(saved.json()["quantity_per_hanger"]) == ["3000"]
        finally:
            app.dependency_overrides.clear()
    finally:
        await engine.dispose()
        await drop_migration_db(db_name)


