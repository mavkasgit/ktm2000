from __future__ import annotations

"""Справочник политик завода (данные, а не код).

Правила, ранее зашитые в сервисы, перенесены сюда как данные (тикет #16):
- токены извлечения цвета при импорте (`COLOR_TOKENS`);
- тексты ошибок валидации плана (`VALIDATION_ERROR_MESSAGES`);
- значение признака «парная обработка» техкарт (`PAIRED_PROCESSING_VALUE`);
- правило округления количества до подвески (`HANGER_ROUNDING_RULE`).

Сервисы применяют эти данные, не зная их содержания.
"""

COLOR_TOKENS: list[dict[str, str]] = [
    {"token": "анод.серебро", "color": "серебро"},
    {"token": "анодсеребро", "color": "серебро"},
    {"token": "анодчёрный", "color": "черный"},
    {"token": "анодчерный", "color": "черный"},
    {"token": "анодшампань", "color": "шампань"},
    {"token": "анодтитан", "color": "титан"},
    {"token": "анодзолото", "color": "золото"},
    {"token": "анодбронза", "color": "бронза"},
    {"token": "анодмедь", "color": "медь"},
    {"token": "анодмед", "color": "медь"},
]

VALIDATION_ERROR_MESSAGES: dict[str, str] = {
    "product_not_found": "Продукт не найден",
    "quantity_must_be_positive": "Количество должно быть положительным",
    "product_inactive": "Продукт неактивен",
    "active_techcard_not_found": "Не найдена активная техкарта для продукта",
    "active_techcard_has_no_lines": "Техкарта не содержит операций",
    "route_not_found": "Не найден маршрут для позиции",
    "no_route_candidate": "Не найден маршрут, удовлетворяющий правилам выбора",
    "route_rule_conflict": "Правила выбора маршрута конфликтуют",
    "route_contains_excluded_step": "Маршрут содержит запрещенный правилами участок",
    "selection_rules": "Маршрут выбран правилами",
    "route_signature_incomplete": "Сигнатура маршрута позиции неполная",
    "active_route_has_no_steps": "Маршрут не содержит этапов",
    "route_sequence_invalid": "Неверная последовательность этапов в маршруте",
    "route_contains_inactive_section": "Маршрут содержит неактивный участок",
    "duplicate_sku_due_date": "Дубликат строки Excel: такая же строка уже есть в плане.",
    "route_not_matching_import_signature": "Маршрут не совпадает с ожидаемым",
    "route_missing_required_step": "В маршруте отсутствует обязательный этап",
    "route_missing_pack_additional_operation": "В маршруте нет дополнительной операции упаковки",
    "route_primary_operation_mismatch": "Основная операция маршрута не совпадает с импортированной. Проверьте соответствие техкарты и маршрута.",
    "active_route_not_found": "Не найден активный маршрут",
    "manual_route_not_found": "Ручной маршрут не найден",
    "manual_route_inactive": "Ручной маршрут неактивен",
    "auto_fallback": "Маршрут скорректирован автоматически — проверьте корректность",
}

PAIRED_PROCESSING_VALUE: str = "paired_processing"
STANDART_PROCESSING_VALUE: str = "standart_processing"

HANGER_ROUNDING_RULE: dict[str, bool | str] = {
    "enabled": True,
    "mode": "round_up_to_multiple",
}
