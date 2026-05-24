from decimal import Decimal

import pytest

from app.services.hanger_quantity import adjust_quantity_to_hanger


class TestAdjustQuantityToHanger:
    """Тесты функции adjust_quantity_to_hanger."""

    def test_quantity_already_multiple(self):
        """Количество уже кратно — возвращает None."""
        assert adjust_quantity_to_hanger(Decimal("10"), 5) is None
        assert adjust_quantity_to_hanger(Decimal("20"), 5) is None
        assert adjust_quantity_to_hanger(Decimal("12"), 4) is None

    def test_quantity_rounds_up(self):
        """Количество округляется вверх до кратного."""
        assert adjust_quantity_to_hanger(Decimal("12"), 5) == Decimal("15")
        assert adjust_quantity_to_hanger(Decimal("13"), 5) == Decimal("15")
        assert adjust_quantity_to_hanger(Decimal("11"), 4) == Decimal("12")
        assert adjust_quantity_to_hanger(Decimal("1"), 8) == Decimal("8")

    def test_quantity_per_hanger_none(self):
        """quantity_per_hanger не задан — возвращает None."""
        assert adjust_quantity_to_hanger(Decimal("12"), None) is None

    def test_quantity_per_hanger_zero(self):
        """quantity_per_hanger = 0 — возвращает None."""
        assert adjust_quantity_to_hanger(Decimal("12"), 0) is None

    def test_quantity_per_hanger_negative(self):
        """quantity_per_hanger < 0 — возвращает None."""
        assert adjust_quantity_to_hanger(Decimal("12"), -5) is None

    def test_quantity_zero(self):
        """quantity = 0 — возвращает None."""
        assert adjust_quantity_to_hanger(Decimal("0"), 5) is None

    def test_quantity_negative(self):
        """quantity < 0 — возвращает None."""
        assert adjust_quantity_to_hanger(Decimal("-5"), 5) is None

    def test_decimal_quantity(self):
        """Работает с десятичными количествами."""
        assert adjust_quantity_to_hanger(Decimal("12.5"), 5) == Decimal("15")
        assert adjust_quantity_to_hanger(Decimal("10.1"), 5) == Decimal("15")

    def test_large_quantity(self):
        """Работает с большими количествами."""
        assert adjust_quantity_to_hanger(Decimal("1234"), 7) == Decimal("1239")
        assert adjust_quantity_to_hanger(Decimal("10000"), 3) == Decimal("10002")

    def test_quantity_per_hanger_one(self):
        """quantity_per_hanger = 1 — всегда кратно, возвращает None."""
        assert adjust_quantity_to_hanger(Decimal("12"), 1) is None
        assert adjust_quantity_to_hanger(Decimal("100"), 1) is None
