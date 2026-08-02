"""Gate-тест целостности сидов (ADR-0004, тикет #22).

Запускается первым в CI. Проверяет, что build_plant_config() собирается
из РЕАЛЬНЫХ данных и все cross-ref правила проходят.
"""

from __future__ import annotations

from app.seeds.canon import build_plant_config
from app.seeds.canon.models import PlantConfig


class TestSeedIntegrity:
    """build_plant_config() собирается, cross-ref проходят."""

    def test_build_plant_config_succeeds(self) -> None:
        """PlantConfig собирается из реальных данных без ошибок."""
        config = build_plant_config()
        assert isinstance(config, PlantConfig)

    def test_color_tokens_non_empty(self) -> None:
        """Цветовые токены загружены."""
        config = build_plant_config()
        assert len(config.display.colors.tokens) > 0

    def test_color_tokens_no_duplicates(self) -> None:
        """Правило 2: нет дублей token в наборе."""
        config = build_plant_config()
        tokens = [t.token for t in config.display.colors.tokens]
        assert len(tokens) == len(set(tokens))

    def test_color_tokens_required_fields(self) -> None:
        """Правило 3: обязательные поля не пустые."""
        config = build_plant_config()
        for t in config.display.colors.tokens:
            assert t.token.strip()
            assert t.color.strip()

    def test_error_messages_non_empty(self) -> None:
        """Тексты ошибок валидации загружены."""
        config = build_plant_config()
        assert len(config.display.labels.error_messages) > 0

    def test_error_messages_keys_non_blank(self) -> None:
        """Правило 3: ключи error_messages не пустые."""
        config = build_plant_config()
        for key in config.display.labels.error_messages:
            assert key.strip()

    def test_hanger_rounding_enum_valid(self) -> None:
        """Правило 6: mode содержит допустимое значение."""
        config = build_plant_config()
        assert config.production.hanger_rounding.mode == "round_up_to_multiple"

    def test_processing_flags_non_empty(self) -> None:
        """Правило 3: значения флагов обработки не пустые."""
        config = build_plant_config()
        assert config.production.processing_flags.paired.strip()
        assert config.production.processing_flags.standart.strip()

    def test_config_is_immutable_snapshot(self) -> None:
        """Два вызова дают эквивалентный результат (детерминизм)."""
        c1 = build_plant_config()
        c2 = build_plant_config()
        assert c1 == c2

    # ─── Sections + Ops cross-ref (тикет #23) ─────────────────────────────

    def test_sections_non_empty(self) -> None:
        """Участки загружены."""
        config = build_plant_config()
        assert len(config.production.sections) > 0

    def test_sections_no_duplicate_codes(self) -> None:
        """Правило 2: нет дублей code в sections."""
        config = build_plant_config()
        codes = [s.code for s in config.production.sections]
        assert len(codes) == len(set(codes))

    def test_ops_reference_valid_sections(self) -> None:
        """Правило 1: все section_code в ops существуют в sections."""
        config = build_plant_config()
        section_codes = {s.code for s in config.production.sections}
        for op in config.production.ops:
            assert op.section_code in section_codes, (
                f"Op '{op.operation_code}' → unknown section '{op.section_code}'"
            )

    def test_ops_unique_within_section(self) -> None:
        """Правило 4: operation_code уникален в рамках section."""
        config = build_plant_config()
        seen: set[tuple[str, str]] = set()
        for op in config.production.ops:
            if op.operation_code is None:
                continue
            key = (op.section_code, op.operation_code)
            assert key not in seen, f"Duplicate op: {key}"
            seen.add(key)

    def test_transforming_ops_reference_valid(self) -> None:
        """TransformingOpRef ссылаются на существующие (section, op)."""
        config = build_plant_config()
        section_codes = {s.code for s in config.production.sections}
        op_keys = {
            (op.section_code, op.operation_code)
            for op in config.production.ops
            if op.operation_code is not None
        }
        for ref in config.production.transforming_ops:
            assert ref.section_code in section_codes
            assert (ref.section_code, ref.operation_code) in op_keys
