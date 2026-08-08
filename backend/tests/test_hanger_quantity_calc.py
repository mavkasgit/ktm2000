"""Unit-тесты чистого движка авторасчёта количества на подвес (#62).

Таблицы вход/выход + границы (0 результат, несовместимость, большие
значения) + валидация констант. Без БД.
"""

import pytest

from app.services.hanger_quantity_calc import (
    DEFAULT_HANGER_SETTINGS,
    HangerCalcResult,
    HangerConfigError,
    HangerSettings,
    compute_hanger_quantity,
)


def _non_calculable() -> HangerCalcResult:
    return HangerCalcResult(
        by_area=None,
        by_size=None,
        total=None,
        limiter=None,
        area_m2=None,
        is_calculable=False,
    )


class TestComputeHangerQuantityCustomerMethod:
    """Методика заказчика: пример ЮП-460 → 72/72/72."""

    def test_customer_example_yup_460(self):
        result = compute_hanger_quantity(
            perimeter_mm=64.2,
            mount_width_mm=19.35,
            length_mm=2800,
        )
        assert result.by_area == 72
        assert result.by_size == 72
        assert result.total == 72
        assert result.limiter == "area"
        assert result.is_calculable is True
        assert result.area_m2 == pytest.approx(0.17976)

    def test_defaults_are_13_1450_20_2(self):
        assert DEFAULT_HANGER_SETTINGS.area_limit_m2 == 13.0
        assert DEFAULT_HANGER_SETTINGS.rod_length_mm == 1450.0
        assert DEFAULT_HANGER_SETTINGS.gap_mm == 20.0
        assert DEFAULT_HANGER_SETTINGS.rod_count == 2

    def test_size_is_limiter(self):
        result = compute_hanger_quantity(
            perimeter_mm=10,
            mount_width_mm=300,
            length_mm=1000,
        )
        # by_area = floor(13/(10*1000/1e6)) = floor(1300) = 1300
        # by_size = floor(1450/(300+20))*2 = floor(4.53)*2 = 8
        assert result.by_area == 1300
        assert result.by_size == 8
        assert result.total == 8
        assert result.limiter == "size"

    def test_area_is_limiter(self):
        result = compute_hanger_quantity(
            perimeter_mm=500,
            mount_width_mm=10,
            length_mm=3000,
        )
        # by_area = floor(13/(500*3000/1e6)) = floor(13/1.5) = 8
        # by_size = floor(1450/(10+20))*2 = floor(48.33)*2 = 96
        assert result.by_area == 8
        assert result.by_size == 96
        assert result.total == 8
        assert result.limiter == "area"

    def test_area_m2_for_reference(self):
        result = compute_hanger_quantity(
            perimeter_mm=100,
            mount_width_mm=100,
            length_mm=2500,
        )
        assert result.area_m2 == pytest.approx(0.25)


class TestCustomHangerSettings:
    """Константы всегда передаются параметром, дефолты — в коде."""

    def test_custom_constants_change_result(self):
        hanger = HangerSettings(area_limit_m2=10, rod_length_mm=2000, gap_mm=0, rod_count=1)
        result = compute_hanger_quantity(
            perimeter_mm=100,
            mount_width_mm=100,
            length_mm=1000,
            hanger=hanger,
        )
        # by_area = floor(10/(100*1000/1e6)) = floor(10/0.1) = 100
        # by_size = floor(2000/(100+0))*1 = 20
        assert result.by_area == 100
        assert result.by_size == 20
        assert result.total == 20
        assert result.limiter == "size"

    def test_rod_count_scales_by_size(self):
        hanger = HangerSettings(rod_count=4)
        single = compute_hanger_quantity(
            perimeter_mm=10,
            mount_width_mm=300,
            length_mm=1000,
        )
        quadruple = compute_hanger_quantity(
            perimeter_mm=10,
            mount_width_mm=300,
            length_mm=1000,
            hanger=hanger,
        )
        assert single.by_size == 8
        assert quadruple.by_size == 16  # ×4 vs ×2 → вдвое больше
        assert quadruple.by_area == single.by_area


class TestNotCalculable:
    """Нерасчётные данные → is_calculable=false, поля null, без исключений."""

    @pytest.mark.parametrize(
        ("perimeter_mm", "mount_width_mm", "length_mm"),
        [
            (None, 19.35, 2800),
            (64.2, None, 2800),
            (64.2, 19.35, None),
            (64.2, 19.35, 0),
            (64.2, 19.35, -5),
            (0, 19.35, 2800),
            (64.2, 0, 2800),
            (None, None, None),
            (float("nan"), 19.35, 2800),
            (64.2, float("inf"), 2800),
            (64.2, 19.35, float("-inf")),
        ],
    )
    def test_missing_fields(self, perimeter_mm, mount_width_mm, length_mm):
        assert compute_hanger_quantity(
            perimeter_mm=perimeter_mm,
            mount_width_mm=mount_width_mm,
            length_mm=length_mm,
        ) == _non_calculable()

    def test_missing_fields_with_incompatible_mount_width_is_still_not_calculable(self):
        # Габарит не влезает на клюшку, но данных для расчёта нет (нет длины) —
        # это нерасчётный item, исключений не бросаем.
        result = compute_hanger_quantity(
            perimeter_mm=64.2,
            mount_width_mm=5000,
            length_mm=None,
        )
        assert result == _non_calculable()


class TestBoundaries:
    """Границы: 0 результат, несовместимость, большие значения."""

    def test_zero_total_by_area(self):
        result = compute_hanger_quantity(
            perimeter_mm=100,
            mount_width_mm=100,
            length_mm=200_000,
        )
        # area_m2 = 100*200000/1e6 = 20 → by_area = floor(13/20) = 0
        assert result.by_area == 0
        assert result.by_size == 24
        assert result.total == 0
        assert result.is_calculable is True  # расчёт возможен, результат — 0

    def test_cross_field_incompatibility_raises(self):
        # 2000 + 20 > 1450 → не влезает на клюшку
        with pytest.raises(HangerConfigError, match="Несовместимые данные"):
            compute_hanger_quantity(
                perimeter_mm=64.2,
                mount_width_mm=2000,
                length_mm=2800,
            )

    def test_cross_field_boundary_fits(self):
        # ровно rod_length (1450): 1430 + 20 = 1450 → не строго больше, допустимо
        result = compute_hanger_quantity(
            perimeter_mm=64.2,
            mount_width_mm=1430,
            length_mm=2800,
        )
        assert result.is_calculable is True

    def test_large_values_no_overflow(self):
        result = compute_hanger_quantity(
            perimeter_mm=1_000_000,
            mount_width_mm=1000,
            length_mm=1_000_000,
        )
        assert result.by_area == 0
        assert result.total == 0
        assert result.is_calculable is True

    def test_very_small_perimeter_large_by_area(self):
        result = compute_hanger_quantity(
            perimeter_mm=0.1,
            mount_width_mm=100,
            length_mm=100,
        )
        # floor(13/(0.1*100/1e6)) = floor(13/1e-5) = 1_300_000
        assert result.by_area == 1_300_000


class TestConstantValidation:
    """Валидация констант на входе: area>0, rod>0, gap>=0, rod_count>=1."""

    @pytest.mark.parametrize(
        "hanger",
        [
            HangerSettings(area_limit_m2=0),
            HangerSettings(area_limit_m2=-1),
            HangerSettings(rod_length_mm=0),
            HangerSettings(rod_length_mm=-100),
            HangerSettings(gap_mm=-1),
            HangerSettings(rod_count=0),
            HangerSettings(area_limit_m2=float("nan")),
            HangerSettings(rod_length_mm=float("inf")),
            HangerSettings(gap_mm=float("-inf")),
        ],
    )
    def test_invalid_constants_raise(self, hanger):
        with pytest.raises(HangerConfigError):
            compute_hanger_quantity(
                perimeter_mm=64.2,
                mount_width_mm=19.35,
                length_mm=2800,
                hanger=hanger,
            )

    def test_valid_constants_do_not_raise(self):
        compute_hanger_quantity(
            perimeter_mm=64.2,
            mount_width_mm=19.35,
            length_mm=2800,
            hanger=HangerSettings(gap_mm=0, rod_count=1),
        )
