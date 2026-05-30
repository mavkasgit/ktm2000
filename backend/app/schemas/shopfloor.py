"""
schemas/shopfloor.py
====================
Pydantic-схемы для Shop Floor API.

ПРИНЦИПЫ ПРОЕКТИРОВАНИЯ СХЕМ:
  1. Вложенный объект SourceSignature — намеренное разделение.
     "Рабочие" поля (qty, status) отделены от "группировочных" (signature).
     Фронтенд сразу видит границу: что использовать для отображения,
     а что — для вычисления ключа группировки.

  2. qty_plan / qty_done возвращаются как str (строковое представление Decimal).
     Причина: JSON не умеет в Decimal, float теряет точность.
     На фронтенде parseFloat() достаточно для отображения,
     но для суммирования используем Number(...).toFixed(2).

  3. source_payload — dict[str, Any], не типизированный объект.
     Содержимое зависит от операции и заполняется при создании позиции плана.
     Типизация на уровне TypeScript (Record<string, string | number | null>).
"""

from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# Перечисления
# ---------------------------------------------------------------------------

class TaskStatus(StrEnum):
    """
    Статус задачи на участке.

    ВАЖНО: Значения должны совпадать с PostgreSQL ENUM или строковыми
    константами в БД. StrEnum даёт строковую сериализацию автоматически.
    """
    PENDING    = "pending"     # Ожидает — в плане, но не начата
    IN_WORK    = "in_work"     # В работе — оператор начал выполнение
    DONE       = "done"        # Завершена — qty_done >= qty_plan
    PARTIALLY  = "partially"   # Частично — qty_done > 0, но < qty_plan
    BLOCKED    = "blocked"     # Заблокирована — предыдущая операция не завершена


# ---------------------------------------------------------------------------
# SourceSignature — блок полей для группировки
# ---------------------------------------------------------------------------

class SourceSignature(BaseModel):
    """
    Сигнатура задачи — полный набор полей для принятия решения о группировке.

    ПОЛЯ:
      input_sku        — артикул, который берём на входе операции
                         (из склада WIP или от предыдущего участка)
      output_sku       — артикул, который производим
                         Отличается от input_sku при трансформирующих операциях:
                         анодирование: "ЮП-460" → "ЮП-460-СР"
                         порезка:      "ЮП-460-СР" → "ЮП-460-СР-3000"

      display_sku      — человекочитаемое поле для UI:
                         "ЮП-460" (если артикул не меняется)
                         "ЮП-460 → ЮП-460-СР" (если трансформация)
                         Вычисляется в SQL через CASE WHEN.

      operation_code   — код операции для различения задач с одинаковым SKU:
                         "press_window" vs "press_comb" — оба дают ЮП-460,
                         но это РАЗНЫЕ операции → должны быть в разных группах

      output_kind      — тип/цвет выходного продукта:
                         "silver", "black" для анодирования
                         Позволяет группировать по цвету при одинаковом SKU

      source_ref       — ссылка на исходную строку заказа/плана.
                         Например: "ЗКЗ-2024-1241/5" (заказ/строка)
                         Используется для профиля "разбить до уровня заказа"

      source_payload   — произвольные доп. поля в JSONB.
                         Примеры ключей:
                           die_id: "M-44"         (матрица пресса)
                           bath_id: "B-3"         (ванна анодирования)
                           customer_ref: "К-777"  (ссылка покупателя)
                         Пользователь может выбрать любой ключ как критерий

      source_fingerprint — 12-символьный SHA1-хеш всех значимых полей.
                           Уникален для каждой комбинации:
                           input_sku + output_sku + operation_code
                           Используется профилем "Полная сигнатура".
    """
    input_sku: str
    output_sku: str
    display_sku: str
    operation_code: str | None = None
    operation_name: str | None = None
    is_significant: bool = False
    source_ref: str | None = None
    source_payload: dict[str, Any] = {}
    source_fingerprint: str


# ---------------------------------------------------------------------------
# SectionBoardTaskOut — основная схема ответа
# ---------------------------------------------------------------------------

class SectionBoardTaskOut(BaseModel):
    """
    Одна задача на доске участка.

    Намеренно НЕ содержит вычисленных агрегатов (totalQtyPlan и т.д.) —
    агрегация происходит на фронтенде при группировке.
    """
    id: int
    plan_position_id: int

    # Маршрут
    route_step_id: int
    route_step_sequence: int   # Порядок операции в маршруте (1, 2, 3...)

    # Количество — строки для сохранения точности Decimal
    qty_plan: str
    qty_done: str

    status: TaskStatus

    # Весь блок группировочных полей — вложен, чтобы отделить от рабочих полей
    signature: SourceSignature

    @field_validator("qty_plan", "qty_done", mode="before")
    @classmethod
    def decimal_to_str(cls, v: Any) -> str:
        """
        Конвертируем Decimal → str при сериализации.
        SQLAlchemy возвращает Decimal из numeric-колонок PostgreSQL.
        JSON не умеет в Decimal, поэтому явно конвертируем.
        """
        if isinstance(v, Decimal):
            return str(v)
        return str(v) if v is not None else "0"

    model_config = {
        "from_attributes": True,   # Позволяет создавать из SQLAlchemy Row
    }


# ---------------------------------------------------------------------------
# Запросы к API
# ---------------------------------------------------------------------------

class SectionBoardQuery(BaseModel):
    """Параметры запроса доски участка."""
    section_id: int
    date_from: str   # ISO format: "2024-01-15"
    date_to: str     # ISO format: "2024-01-21"


class SectionPayloadKeysOut(BaseModel):
    """Список уникальных ключей source_payload для участка."""
    keys: list[str]
