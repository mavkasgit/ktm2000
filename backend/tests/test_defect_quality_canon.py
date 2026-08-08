"""Per-consumer тесты карты брака (тикет #25).

resolve_defect_status читает данные из config (а не хардкодит): fake карта
≠ prod → сервис должен вернуть fake-значения. Плюс тест сидера defect_types.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.defect import DefectDecisionType, DefectType
from app.seeds.canon.models import (
    DefectDecisionDef,
    DefectDecisionMap,
    DefectTypeDef,
    QualityCanon,
)
from app.seeds.canon.registry import build_plant_config
from app.seeds.seeders.defect_types_seeder import seed_defect_types
from app.services.shopfloor.operations_defects import resolve_defect_status


class TestResolveDefectStatusWithFakeConfig:
    """Сервис использует карту из config, а не prod-значения."""

    def _fake_config(self):
        fake_quality = QualityCanon(
            defect_decision_map=DefectDecisionMap(
                mapping={
                    "scrap": DefectDecisionDef(status="returned", reason="return_to_previous"),
                    "rework_current": DefectDecisionDef(status="closed", reason="complete"),
                }
            )
        )
        return build_plant_config().model_copy(update={"quality": fake_quality})

    def test_scrap_resolves_to_fake_entry(self) -> None:
        cfg = self._fake_config()
        entry = resolve_defect_status(DefectDecisionType.scrap, cfg.quality.defect_decision_map.mapping)
        assert entry is not None
        assert entry.status == "returned"
        assert entry.reason == "return_to_previous"

    def test_rework_current_resolves_to_fake_entry(self) -> None:
        cfg = self._fake_config()
        entry = resolve_defect_status(DefectDecisionType.rework_current, cfg.quality.defect_decision_map.mapping)
        assert entry is not None
        assert entry.status == "closed"
        assert entry.reason == "complete"

    def test_unknown_decision_returns_none(self) -> None:
        cfg = self._fake_config()
        entry = resolve_defect_status(DefectDecisionType.accept_with_deviation, cfg.quality.defect_decision_map.mapping)
        assert entry is None

    def test_prod_map_differs_from_fake(self) -> None:
        """Контроль: prod-карта отличается от fake (иначе тест бессмыслен)."""
        prod = build_plant_config().quality.defect_decision_map.mapping["scrap"]
        assert prod.status == "scrapped"
        assert prod.reason == "scrap"


@pytest.mark.asyncio
async def test_seed_defect_types_upserts(session) -> None:
    """Сидер заполняет таблицу defect_types из канона."""
    config = build_plant_config()
    count = await seed_defect_types(session, config.quality.defect_types)
    await session.commit()

    assert count == len(config.quality.defect_types)
    rows = (await session.execute(select(DefectType))).scalars().all()
    assert len(rows) == count
    by_code = {row.code: row for row in rows}
    assert by_code["SCRATCH"].name == "Царапина"
    assert by_code["ANOD_FILM"].requires_quality_decision is True

    # Идемпотентность
    count2 = await seed_defect_types(session, config.quality.defect_types)
    await session.commit()
    rows2 = (await session.execute(select(DefectType))).scalars().all()
    assert len(rows2) == count
    assert count2 == count


@pytest.mark.asyncio
async def test_seed_defect_types_model_contract(session) -> None:
    """Сидер принимает DefectTypeDef модели, а не dict."""
    custom = [
        DefectTypeDef(code="CUSTOM", name="Свой тип", category="other", severity=1),
    ]
    count = await seed_defect_types(session, custom)
    await session.commit()
    assert count == 1
    row = await session.scalar(select(DefectType).where(DefectType.code == "CUSTOM"))
    assert row is not None
    assert row.name == "Свой тип"
