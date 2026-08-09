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
    compute_paired_hanger_quantity,
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


class TestComputePairedHangerQuantity:
    """Совместный расчёт парной техкарты (#58/#67).

    by_area = floor(13 / ((perimeter_A + perimeter_B) × длина / 10⁶)),
    by_size = floor(2900 / (габарит_A + габарит_B + 40)), итог = min.
    Единые константы (те же HangerSettings, что у одиночного расчёта).
    """

    def test_customer_method_pair_of_identical_articles(self):
        # Пара двух одинаковых ЮП-460 (64,2 / 19,35 / 2800).
        result = compute_paired_hanger_quantity(
            perimeter_a_mm=64.2,
            mount_width_a_mm=19.35,
            perimeter_b_mm=64.2,
            mount_width_b_mm=19.35,
            length_mm=2800,
        )
        # by_area = floor(13 / ((64,2+64,2)×2800/10⁶)) = floor(13/0,35952) = 36
        # by_size = floor(2900 / (19,35+19,35+40)) = floor(2900/78,7) = 36
        assert result.by_area == 36
        assert result.by_size == 36
        assert result.total == 36
        assert result.limiter == "area"
        assert result.is_calculable is True
        assert result.area_m2 == pytest.approx(0.35952)

    def test_different_articles_sum_dimensions(self):
        # A: 50/10, B: 30/20, длина 2000.
        result = compute_paired_hanger_quantity(
            perimeter_a_mm=50,
            mount_width_a_mm=10,
            perimeter_b_mm=30,
            mount_width_b_mm=20,
            length_mm=2000,
        )
        # by_area = floor(13 / (80×2000/10⁶)) = floor(13/0,16) = 81
        # by_size = floor(2900 / (10+20+40)) = floor(2900/70) = 41
        assert result.by_area == 81
        assert result.by_size == 41
        assert result.total == 41
        assert result.limiter == "size"

    def test_pair_half_the_single_quantity(self):
        # Одиночный ЮП-460 даёт 72; пара двух таких же — половину (36):
        # пара занимает на подвесе вдвое больше места.
        single = compute_hanger_quantity(
            perimeter_mm=64.2,
            mount_width_mm=19.35,
            length_mm=2800,
        )
        paired = compute_paired_hanger_quantity(
            perimeter_a_mm=64.2,
            mount_width_a_mm=19.35,
            perimeter_b_mm=64.2,
            mount_width_b_mm=19.35,
            length_mm=2800,
        )
        assert single.total == 72
        assert paired.total == 36

    def test_uses_defaults_13_1450_20_2(self):
        # Дефолты = константы заказчика: 2900 = 1450×2, 40 = 20×2.
        hanger = HangerSettings()
        result = compute_paired_hanger_quantity(
            perimeter_a_mm=50,
            mount_width_a_mm=10,
            perimeter_b_mm=30,
            mount_width_b_mm=20,
            length_mm=2000,
            hanger=hanger,
        )
        assert result.by_size == 41
        assert result.total == 41

    def test_custom_constants_scale_pair(self):
        hanger = HangerSettings(area_limit_m2=10, rod_length_mm=2000, gap_mm=0, rod_count=1)
        result = compute_paired_hanger_quantity(
            perimeter_a_mm=100,
            mount_width_a_mm=100,
            perimeter_b_mm=100,
            mount_width_b_mm=100,
            length_mm=1000,
            hanger=hanger,
        )
        # by_area = floor(10 / (200×1000/10⁶)) = floor(10/0,2) = 50
        # by_size = floor(2000×1 / (100+100+0)) = floor(2000/200) = 10
        assert result.by_area == 50
        assert result.by_size == 10
        assert result.total == 10
        assert result.limiter == "size"


class TestPairedNotCalculable:
    """Нерасчётные данные пары → is_calculable=false, поля null, без исключений."""

    @pytest.mark.parametrize(
        ("perimeter_a_mm", "mount_width_a_mm", "perimeter_b_mm", "mount_width_b_mm", "length_mm"),
        [
            (None, 19.35, 64.2, 19.35, 2800),
            (64.2, None, 64.2, 19.35, 2800),
            (64.2, 19.35, None, 19.35, 2800),
            (64.2, 19.35, 64.2, None, 2800),
            (64.2, 19.35, 64.2, 19.35, None),
            (64.2, 19.35, 64.2, 19.35, 0),
            (0, 19.35, 64.2, 19.35, 2800),
            (64.2, -5, 64.2, 19.35, 2800),
            (float("nan"), 19.35, 64.2, 19.35, 2800),
            (64.2, float("inf"), 64.2, 19.35, 2800),
        ],
    )
    def test_missing_fields(
        self, perimeter_a_mm, mount_width_a_mm, perimeter_b_mm, mount_width_b_mm, length_mm
    ):
        assert compute_paired_hanger_quantity(
            perimeter_a_mm=perimeter_a_mm,
            mount_width_a_mm=mount_width_a_mm,
            perimeter_b_mm=perimeter_b_mm,
            mount_width_b_mm=mount_width_b_mm,
            length_mm=length_mm,
        ) == _non_calculable()

    def test_missing_field_with_incompatible_widths_is_still_not_calculable(self):
        # Габариты не влезают, но данных для расчёта нет (нет длины) —
        # это нерасчётный item, исключений не бросаем.
        result = compute_paired_hanger_quantity(
            perimeter_a_mm=64.2,
            mount_width_a_mm=5000,
            perimeter_b_mm=64.2,
            mount_width_b_mm=5000,
            length_mm=None,
        )
        assert result == _non_calculable()


class TestPairedBoundaries:
    """Границы пары: 0 результат, несовместимость, большие значения."""

    def test_zero_total_by_area(self):
        result = compute_paired_hanger_quantity(
            perimeter_a_mm=100,
            mount_width_a_mm=10,
            perimeter_b_mm=100,
            mount_width_b_mm=10,
            length_mm=200_000,
        )
        # area_m2 = 200×200000/10⁶ = 40 → by_area = floor(13/40) = 0
        # by_size = floor(2900/(10+10+40)) = floor(2900/60) = 48
        assert result.by_area == 0
        assert result.by_size == 48
        assert result.total == 0
        assert result.is_calculable is True

    def test_cross_field_incompatibility_raises(self):
        # 1500 + 1500 + 40 = 3040 > 2900 → пара не влезает на подвес суммарно.
        with pytest.raises(HangerConfigError, match="Несовместимые данные"):
            compute_paired_hanger_quantity(
                perimeter_a_mm=64.2,
                mount_width_a_mm=1500,
                perimeter_b_mm=64.2,
                mount_width_b_mm=1500,
                length_mm=2800,
            )

    def test_cross_field_boundary_fits(self):
        # 1430 + 1430 + 40 = 2900 → не строго больше, допустимо (by_size = 1).
        result = compute_paired_hanger_quantity(
            perimeter_a_mm=64.2,
            mount_width_a_mm=1430,
            perimeter_b_mm=64.2,
            mount_width_b_mm=1430,
            length_mm=2800,
        )
        assert result.is_calculable is True
        assert result.by_size == 1

    def test_large_values_no_overflow(self):
        result = compute_paired_hanger_quantity(
            perimeter_a_mm=1_000_000,
            mount_width_a_mm=1000,
            perimeter_b_mm=1_000_000,
            mount_width_b_mm=1000,
            length_mm=1_000_000,
        )
        assert result.by_area == 0
        assert result.total == 0
        assert result.is_calculable is True

    @pytest.mark.parametrize(
        "hanger",
        [
            HangerSettings(area_limit_m2=0),
            HangerSettings(rod_length_mm=0),
            HangerSettings(gap_mm=-1),
            HangerSettings(rod_count=0),
            HangerSettings(area_limit_m2=float("nan")),
        ],
    )
    def test_invalid_constants_raise(self, hanger):
        with pytest.raises(HangerConfigError):
            compute_paired_hanger_quantity(
                perimeter_a_mm=64.2,
                mount_width_a_mm=19.35,
                perimeter_b_mm=64.2,
                mount_width_b_mm=19.35,
                length_mm=2800,
                hanger=hanger,
            )
