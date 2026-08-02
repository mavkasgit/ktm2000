// GENERATED FILE — do not edit by hand. Regenerate: python scripts/generate_frontend_labels.py

// Лейблы статусов позиции плана
export const statusLabels: Record<string, string> = {
  "approved": "Утверждён",
  "cancelled": "Отменён",
  "draft": "Черновик",
  "invalid": "Ошибка",
  "released": "Запущен",
  "valid": "Валиден",
}

// Лейблы видов выпуска
export const outputKindLabels: Record<string, string> = {
  "finished_good": "Готовая продукция",
  "semi_finished_shipment": "Полуфабрикат",
  "ГП": "Готовая продукция",
  "П/ф": "Полуфабрикат",
}

// Тексты ошибок валидации (ключи — error codes сервера)
export const errorLabels: Record<string, string> = {
  "active_route_has_no_steps": "Маршрут не содержит этапов",
  "active_techcard_has_no_lines": "Техкарта не содержит операций",
  "active_techcard_not_found": "Не найдена активная техкарта для продукта",
  "duplicate_sku_due_date": "Дубликат строки Excel: такая же строка уже есть в плане.",
  "no_route_candidate": "Не найден маршрут, удовлетворяющий правилам выбора",
  "product_inactive": "Продукт неактивен",
  "product_not_found": "Продукт не найден",
  "quantity_must_be_positive": "Количество должно быть положительным",
  "route_contains_excluded_step": "Маршрут содержит запрещенный правилами участок",
  "route_contains_inactive_section": "Маршрут содержит неактивный участок",
  "route_missing_pack_additional_operation": "В маршруте нет дополнительной операции упаковки",
  "route_missing_required_step": "В маршруте отсутствует обязательный этап",
  "route_not_found": "Не найден маршрут для позиции",
  "route_not_matching_import_signature": "Маршрут не совпадает с ожидаемым",
  "route_primary_operation_mismatch": "Основная операция маршрута не совпадает с импортированной. Проверьте соответствие техкарты и маршрута.",
  "route_rule_conflict": "Правила выбора маршрута конфликтуют",
  "route_sequence_invalid": "Неверная последовательность этапов в маршруте",
  "route_signature_incomplete": "Сигнатура маршрута позиции неполная",
  "selection_rules": "Маршрут выбран правилами",
}

// Каталог ролей: code -> (label, sections)
export interface RoleDef { code: string; label: string; sections: string[] }
export const roles: RoleDef[] = [
  { code: "admin", label: "Администратор", sections: ["/", "/references", "/planning", "/execution", "/section-tasks", "/transfers", "/spg", "/audit-logs", "/settings", "/settings/dev", "/dev"] },
  { code: "planner", label: "Планировщик", sections: ["/", "/references", "/planning", "/execution", "/section-tasks", "/transfers", "/spg", "/audit-logs", "/settings", "/dev"] },
  { code: "section_manager", label: "Начальник участка", sections: ["/", "/references", "/execution", "/section-tasks", "/transfers", "/spg", "/audit-logs", "/settings", "/dev"] },
  { code: "operator", label: "Оператор", sections: ["/", "/references", "/section-tasks", "/transfers", "/spg", "/audit-logs", "/settings", "/dev"] },
  { code: "viewer", label: "Наблюдатель", sections: ["/", "/references", "/section-tasks", "/spg", "/audit-logs", "/settings", "/dev"] },
  { code: "transporter", label: "Транспортировщик", sections: ["/", "/references", "/section-tasks", "/transfers", "/spg", "/audit-logs", "/settings", "/dev"] },
]
