"""Бюджеты передач и отправок — формулы в двух уровнях (decimal + SQL).

Два именованных понятия (тикет #119, CONTEXT.md: Передача ≠ Отправка):
- бюджет **передачи** (``transferable``) — сколько ещё можно передать
  на следующий участок;
- бюджет **отправки** (``sendable``) — сколько ещё можно отправить
  (final release) с финального участка.

Семантика (тикет #106):
- ``remaining_plain(completed, transferred)`` — сколько ещё можно передать
  с обычного производственного задания: только уже завершённое количество
  минус уже переданное. ``received`` в бюджете НЕ участвует (намеренное
  breaking-изменение: раньше ``completed + received - transferred``).
- ``remaining_transform(produced, transferred)`` — сколько ещё можно
  передать выхода трансформирующего задания: фактически раскроенное
  (уже закапленное ``min(output_quantity, produced_by_group)`` на уровне
  ``build_outputs_progress``) минус уже переданное по размеру. Инвариант D2.
- ``remaining_send(produced, released)`` — сколько ещё можно отправить
  с финального участка: произведено минус уже выпущено (FINAL_RELEASE).
- ``remaining_stock(plan_remaining, physical_stock)`` — складская передача:
  нельзя больше плана позиции и больше физического остатка.

SQL-фабрики (``*_qty_sql``) — те же формулы на уровне выражений SQLAlchemy
поверх ledger-примитивов ``stock.ledger.net_*_sq`` (ADR-0017/0018):
потребитель подключает их подзапросами и НЕ копирует формулу; сам
``reverses_id`` вне ledger не интерпретируется. Без скрытого выбора
семантики внутри фабрики — передача или отправка выбирается потребителем
по финальности участка.

Все функции клампят в ноль — бюджет не бывает отрицательным.
"""
from __future__ import annotations
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.sql.elements import ColumnElement


def remaining_plain(completed: Decimal, transferred: Decimal) -> Decimal:
    """Остаток к передаче с обычного задания: ``max(0, completed - transferred)``."""
    return max(Decimal("0"), completed - transferred)


def remaining_transform(produced: Decimal, transferred: Decimal) -> Decimal:
    """Остаток к передаче выхода трансформации: ``max(0, produced - transferred)``.

    ``produced`` приходит уже закапленным ``min(output_quantity,
    produced_by_group)`` из ``build_outputs_progress`` — кап здесь не
    дублируется.
    """
    return max(Decimal("0"), produced - transferred)


def remaining_send(produced: Decimal, released: Decimal) -> Decimal:
    """Остаток к отправке (final release): ``max(0, produced - released)``.

    ``produced`` — фактически произведённое на финальном участке
    (для трансформирующего этапа — закапленный
    ``min(output_quantity, produced_by_group)`` из ``build_outputs_progress``).
    """
    return max(Decimal("0"), produced - released)


def transferable_qty_sql(
    completed_qty: ColumnElement[Decimal],
    transferred_net: ColumnElement[Decimal],
) -> ColumnElement[Decimal]:
    """SQL-форма бюджета передачи: ``greatest(completed - transferred, 0)``.

    Аргументы — уже coalesce'нутые колонки подзапросов ledger
    (``net_transferred_sq`` / completed-aggregate). Одна формула с
    ``remaining_plain``/``remaining_transform``; семантику выбирает
    потребитель, фабрика CASE не строит.
    """
    return func.greatest(completed_qty - transferred_net, 0)


def sendable_qty_sql(
    produced_qty: ColumnElement[Decimal],
    released_net: ColumnElement[Decimal],
) -> ColumnElement[Decimal]:
    """SQL-форма бюджета отправки: ``greatest(produced - released, 0)``.

    Аргументы — уже coalesce'нутые колонки подзапросов ledger
    (``net_by_reason_sq(FINAL_RELEASE)`` / completed-aggregate).
    Одна формула с ``remaining_send``.
    """
    return func.greatest(produced_qty - released_net, 0)


def remaining_stock(plan_remaining: Decimal, physical_stock: Decimal) -> Decimal:
    """Складской остаток к передаче: ``min(plan_remaining, physical_stock)``."""
    return min(plan_remaining, physical_stock)
