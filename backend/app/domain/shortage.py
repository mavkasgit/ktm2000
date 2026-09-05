"""Стратегии недостачи (#133, #134) — единый словарь домена.

До #134 enum жил в ``app.api.routes.shopfloor`` (route-enum), а сервисный
слой повторял его строками: Literal в ``complete_task`` + строковые ветки
``_resolve_shortage``. Новая стратегия правилась в трёх местах.

Теперь канон здесь: FastAPI-схемы, сервис ``complete_task`` и резолвер
недостачи ссылаются на один ``ShortageStrategy``. str-Enum — значения
совпадают с wire-форматом API, старые строковые вызовы совместимы.
"""

from __future__ import annotations

import enum


class ShortageStrategy(str, enum.Enum):
    """Поведение при нехватке GOOD-баланса входной группы трансформации.

    Плановый лимит ``remaining_input`` жёсткий при любой стратегии;
    стратегия — про физику склада (см. ``_resolve_shortage``):

    - ``fail`` — отказ всей операции с указанием доступного количества;
    - ``partial`` — кламп порции до доступного, задача остаётся частично
      выполненной;
    - ``negative_remainder`` — полная порция, баланс участка уходит в минус
      до закрытия последующей выдачей (для СПГ с lot-учётом минус
      блокирует сам StockCommandService).
    """

    fail = "fail"
    partial = "partial"
    negative_remainder = "negative_remainder"


DEFAULT_SHORTAGE_STRATEGY = ShortageStrategy.fail
