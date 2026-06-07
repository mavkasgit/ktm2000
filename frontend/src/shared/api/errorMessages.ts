/**
 * Словарь переводов серверных ошибок на русский.
 *
 * Бэкенд выбрасывает `raise ValueError(...)` и `raise HTTPException(detail=...)`
 * с английскими текстами. Чтобы не трогать сервер (логи, тесты, отладка остаются
 * на английском), переводим на клиенте.
 *
 * Ключи — точные английские строки или шаблоны с плейсхолдерами `{0}`, `{1}`, ...
 * Шаблон используется, когда бэкенд подставляет динамические значения через f-string.
 * `translateError` сам определяет, искать точное совпадение или нормализовать строку
 * в шаблон.
 */

const DICT: Record<string, string> = {
  // === shopfloor / operations_tasks ===
  "Task must be in progress": "Задача должна быть в работе",
  "Task must be ready/in_progress/partially_completed":
    "Задача должна быть в статусе «готова», «в работе» или «частично завершена»",
  "Quantities must be >= 0": "Количество должно быть >= 0",
  "Complete quantity exceeds quantity in work":
    "Количество факта превышает объём «В работе»",
  "Final release allowed only for final route stage":
    "Финальный выпуск разрешён только на финальном этапе маршрута",
  "Final release exceeds releasable quantity":
    "Финальный выпуск превышает доступный к выпуску объём",
  "Plan position not found": "Позиция плана не найдена",
  "Plan position must be released": "Позиция плана должна быть выпущена",
  "No route step found for this section in the plan position":
    "Для этого участка в позиции плана не найден этап маршрута",
  "No excess quantity available for return": "Нет излишков для возврата на склад",
  "Return quantity ({0}) exceeds available for return ({1})":
    "Количество возврата ({0}) превышает доступное к возврату ({1})",
  "Section is not bound to any SPG": "Участок не привязан ни к одной ГХП",
  "Remainder not found": "Остаток не найден",
  "Remainder already consumed": "Остаток уже израсходован",
  "Either section_id or spg_id must be provided":
    "Необходимо указать section_id или spg_id",

  // === shopfloor / common ===
  "Task not found": "Задача не найдена",
  "Transfer not found": "Передача не найдена",
  "Defect not found": "Брак не найден",
  "Route stage not found": "Этап маршрута не найден",
  "Rework task not found": "Задача на доработку не найдена",
  "{0} must be > 0": "{0} должно быть > 0",
  "SpgRemainder {0} not found": "Остаток СГП {0} не найден",
  "RouteStage {0} not found": "Этап маршрута {0} не найден",

  // === shopfloor / operations_defects ===
  "product_id is required for manual defect registration":
    "Для ручной регистрации брака требуется product_id",
  "section_id or route_stage_id is required for manual defect registration":
    "Для ручной регистрации брака требуется section_id или route_stage_id",
  "Rework decisions require an associated work task":
    "Решения по доработке требуют привязанной рабочей задачи",

  // === shopfloor / operations_meta ===
  "Comment body must not be empty": "Текст комментария не должен быть пустым",
  "original_filename is required": "Требуется original_filename",
  "size_bytes must be > 0": "size_bytes должно быть > 0",
  "Attachment not found": "Вложение не найдено",

  // === transfers / services ===
  "Source task plan line not found":
    "Не найдена строка плана исходной задачи",
  "Next route step not found": "Следующий этап маршрута не найден",
  "Transfer tasks must have same product":
    "Задачи передачи должны относиться к одному продукту",
  "Transfer tasks must belong to same plan position":
    "Задачи передачи должны принадлежать одной позиции плана",
  "Transfer target must be next route step":
    "Получатель передачи должен быть следующим этапом маршрута",
  "Transfers within the same Storage Production Group (GHP) are not allowed":
    "Передачи внутри одной группы хранения и производства (ГХП) запрещены",
  "Transfer quantity exceeds transferable amount":
    "Количество передачи превышает доступный к передаче объём",
  "Transfer must be sent": "Передача должна быть отправлена",
  "accepted/rejected must be >= 0": "Принято/отклонено должно быть >= 0",
  "accepted + rejected must be > 0": "Принято + отклонено должно быть > 0",
  "accepted + rejected exceeds sent quantity":
    "Сумма принятого и отклонённого превышает отправленное количество",
  "Transfer discrepancy not found": "Расхождение по передаче не найдено",
  "Defect item not found": "Позиция брака не найдена",
  "Resolve quantity exceeds unresolved discrepancy":
    "Количество разрешения превышает неурегулированное расхождение",
  "Only accepted transfers can be corrected":
    "Корректировать можно только принятые передачи",
  "Only accepted transfers can be cancelled":
    "Отменять можно только принятые передачи",
  "Corrected quantity exceeds transferable amount of source task. Available to transfer: {0}":
    "Скорректированное количество превышает доступный к передаче объём исходной задачи. Доступно к передаче: {0}",
  "Target task has already consumed or issued parts. Cannot reduce transfer by {0} as target task only has {1} available stock":
    "Целевая задача уже использовала или выдала материалы. Нельзя уменьшить передачу на {0}, так как в целевой задаче доступно только {1}",

  // === transfers / api ===
  "Section is locked to single-window context":
    "Режим одного окна разрешает работу только с текущим участком",

  // === production_plan_service ===
  "Change set not found": "Набор изменений не найден",
  "Only applied change sets can be rolled back":
    "Откатить можно только применённые наборы изменений",
  "Cannot rollback: position already released":
    "Нельзя откатить: позиция уже выпущена",
  "Position with status '{0}' cannot be approved":
    "Позиция в статусе «{0}» не может быть утверждена",

  // === plan_generation / release ===
  "Production plan not found": "План производства не найден",
  "Production plan must be approved before release":
    "План производства должен быть утверждён перед выпуском",
  "No approved positions selected": "Не выбрано ни одной утверждённой позиции",
  "Position {0} has no route assigned - cannot release without route":
    "Для позиции {0} не назначен маршрут — выпуск без маршрута невозможен",
  "Route for position {0} is not active":
    "Маршрут для позиции {0} не активен",
  "Release quantity must be > 0": "Количество к выпуску должно быть > 0",
  "Release quantity exceeds approved remaining quantity":
    "Количество к выпуску превышает утверждённый остаток",
  "Release batch not found": "Партия выпуска не найдена",
  "Cancelled release batch cannot be released":
    "Отменённая партия не может быть выпущена",
  "Release batch has no positions": "В партии выпуска нет позиций",
  "Only approved positions can be released":
    "Выпускать можно только утверждённые позиции",
  "Position #{0} has no route assigned":
    "Для позиции #{0} не назначен маршрут",
  "Position #{0}: no paired techcard found for product resolution":
    "Позиция #{0}: не найдена парная техкарта для резолюции продукта",
  "Position #{0}: paired techcard has no component products":
    "Позиция #{0}: парная техкарта не содержит компонентов",
  "Selected plan position not found":
    "Выбранная позиция плана не найдена",
  "Selected plan position must be approved":
    "Выбранная позиция плана должна быть утверждена",
  "Route has no stages": "Маршрут не содержит этапов",
  "Route sequence is invalid":
    "Неверная последовательность этапов маршрута",
  "Route contains inactive section":
    "Маршрут содержит неактивный участок",
  "route_build_error: {0}": "Ошибка построения маршрута: {0}",

  // === production_planning / production_plans ===
  "Position not found": "Позиция не найдена",
  "Position already has execution facts; manual route pass is allowed only before execution starts":
    "По позиции уже есть факты выполнения; ручной пропуск маршрута разрешён только до начала выполнения",
  "Change set does not belong to production plan":
    "Набор изменений не относится к плану производства",
  "Import batch not found": "Пакет импорта не найден",
  "position_ids must not be empty": "position_ids не должны быть пустыми",
  "Route not found": "Маршрут не найден",
  "Route is not active": "Маршрут не активен",
  "Route is inactive": "Маршрут не активен",
  "Some positions not found or belong to a different plan":
    "Некоторые позиции не найдены или относятся к другому плану",
  "Change set for batch not found":
    "Набор изменений для партии не найден",
  "Position does not belong to production plan":
    "Позиция не относится к плану производства",
  "Position status must be approved or released, got '{0}'":
    "Статус позиции должен быть «утверждена» или «выпущена», получено «{0}»",
  "Position has no tasks and cannot be released from current status":
    "У позиции нет задач, выпуск из текущего статуса невозможен",
  "Position has no route tasks": "У позиции нет задач маршрута",
  "target_route_stage_id is required unless complete_route is true":
    "target_route_stage_id обязателен, если complete_route не равно true",
  "target_route_stage_id not found in this position route":
    "target_route_stage_id не найден в маршруте этой позиции",
  "Unable to create route tasks":
    "Не удалось создать задачи маршрута",
  "Manual pass failed at step {0}: {1}":
    "Сбой ручного пропуска на этапе {0}: {1}",

  // === routes / routes_seed ===
  "force=true is not allowed in production":
    "force=true запрещён в продакшне",
  "Route with this name already exists":
    "Маршрут с таким именем уже существует",
  "Sequence must be > 0": "Последовательность должна быть > 0",
  "Inactive section cannot be used in route":
    "Неактивный участок нельзя использовать в маршруте",
  "Only one final step allowed":
    "Допускается только один финальный этап",
  "Section {0} not found": "Участок {0} не найден",
  "Inactive section {0}": "Неактивный участок {0}",

  // === sections ===
  "Section not found": "Участок не найден",
  "Section code already exists": "Код участка уже используется",
  "SPG ID does not exist": "ГХП с таким ID не существует",
  "Group code already exists for this section":
    "Код группы уже используется для этого участка",
  "Operation group not found":
    "Группа операций не найдена",
  "Operation not found in this section":
    "Операция не найдена в этом участке",
  "Target group does not exist":
    "Целевая группа не существует",

  // === spg ===
  "SPG not found": "ГХП не найдена",
  "SPG code already exists": "Код ГХП уже используется",
  "Section does not belong to this SPG":
    "Участок не относится к этой ГХП",
  "Product not found": "Продукт не найден",
  "Quantity must be positive": "Количество должно быть положительным",
  "quantity must be positive": "Количество должно быть положительным",
  "operation_type must be 'in' or 'out'":
    "operation_type должен быть «in» или «out»",
  "actual_quantity must be non-negative":
    "actual_quantity должно быть >= 0",
  "Invalid Excel file: {0}": "Некорректный файл Excel: {0}",
  "Excel sheet is empty": "Лист Excel пуст",
  "No sections associated with this SPG":
    "С этой ГХП не связано ни одного участка",

  // === products ===
  "length_mm must be > 0, got {0}":
    "length_mm должно быть > 0, получено {0}",
  "Unknown processing flag codes: {0}":
    "Неизвестные коды флагов обработки: {0}",
  "Invalid sort field: {0}": "Неизвестное поле сортировки: {0}",
  "Invalid sort order: {0}": "Неизвестный порядок сортировки: {0}",
  "SKU already exists": "Артикул уже используется",
  "No route found for this product":
    "Для этого продукта не найден маршрут",

  // === techcards ===
  "Techcard not found": "Техкарта не найдена",
  "Component product not found": "Продукт-компонент не найден",
  "Techcard has no product_id": "У техкарты не указан product_id",
  "Techcard product not found": "Продукт техкарты не найден",
  "Techcard is inactive": "Техкарта не активна",
  "Techcard has no linked product":
    "У техкарты нет привязанного продукта",

  // === imports / import_templates ===
  "template_id is required": "Требуется template_id",
  "Template not found": "Шаблон не найден",
  "Template is inactive": "Шаблон не активен",
  "Invalid column_mapping JSON: {0}":
    "Некорректный JSON в column_mapping: {0}",
  "column_mapping must be a JSON object":
    "column_mapping должен быть JSON-объектом",
  "File not found": "Файл не найден",
  "File content not available":
    "Содержимое файла недоступно",
  "File not found on disk": "Файл не найден на диске",
  "Import template not found": "Шаблон импорта не найден",
  "Template name is required": "Требуется название шаблона",
  "Template with this code already exists":
    "Шаблон с таким кодом уже существует",

  // === catalog_import ===
  "Only .zip files are accepted":
    "Принимаются только файлы .zip",
  "profiles.db not found in ZIP":
    "profiles.db не найден в архиве ZIP",

  // === demo ===
  "initial_quantity must be > 0": "initial_quantity должно быть > 0",
  "run_id '{0}' already exists. Each run_id must be unique.":
    "run_id «{0}» уже существует. Каждый run_id должен быть уникальным.",
  "target_route_stage_id is required for 'to_step_ready' preset":
    "target_route_stage_id обязателен для пресета «to_step_ready»",
  "Unknown scenario_id '{0}'": "Неизвестный scenario_id «{0}»",
  "No plan position created for test run":
    "Для тестового прогона не создана позиция плана",
  "Created plan position not found":
    "Созданная позиция плана не найдена",
  "Approve failed: {0}": "Сбой утверждения: {0}",
  "Release failed: {0}": "Сбой выпуска: {0}",
  "No tasks created for released position":
    "Для выпущенной позиции не создано ни одной задачи",
  "target_route_stage_id not found in route steps":
    "target_route_stage_id не найден среди этапов маршрута",
  "Task execution failed at step {0}: {1}":
    "Сбой выполнения задачи на этапе {0}: {1}",
  "Transfer failed at step {0}: {1}":
    "Сбой передачи на этапе {0}: {1}",

  // === auth ===
  "Invalid credentials": "Неверные учётные данные",
  "User is disabled": "Пользователь отключён",
  "Insufficient permissions": "Недостаточно прав",

  // === route_rule_profiles / route_selection_rules ===
  "Profile code is required": "Требуется код профиля",
  "Profile name is required": "Требуется название профиля",
  "Profile with this code already exists":
    "Профиль с таким кодом уже существует",
  "Invalid import_template_id": "Некорректный import_template_id",
  "Profile not found": "Профиль не найден",
  "Cannot delete profile: it is used by route selection rules":
    "Нельзя удалить профиль: он используется правилами выбора маршрута",
  "Profile has no route_sections defined":
    "В профиле не определены route_sections",
  "excel_column_passport.index must be positive":
    "excel_column_passport.index должен быть положительным",
  "excel_column_passport has duplicate index values":
    "В excel_column_passport есть дублирующиеся index",
  "excel_column_passport.letter is required":
    "Требуется excel_column_passport.letter",
  "excel_column_passport.header is required":
    "Требуется excel_column_passport.header",
  "excel_column_passport.field_path is required":
    "Требуется excel_column_passport.field_path",

  "Rule with this code already exists":
    "Правило с таким кодом уже существует",
  "Invalid profile_id": "Некорректный profile_id",
  "Rule not found": "Правило не найдено",
  "Rule name is required": "Требуется название правила",
  "At least one action is required":
    "Требуется хотя бы одно действие",
  "Excel condition must define field_path or explicit excel column binding":
    "Условие Excel должно задавать field_path или явную привязку к колонке",
  "excel_column_index must be positive":
    "excel_column_index должен быть положительным",
  "Context condition field_path is required":
    "Требуется field_path у контекстного условия",
  "Condition field_path is required":
    "Требуется field_path у условия",
  "Condition value is required for {0}":
    "Для оператора {0} требуется значение условия",
  "DSL action path must start with 'ctx.'":
    "Путь действия DSL должен начинаться с «ctx.»",
  "{0} requires section_id": "{0} требует section_id",
  "{0} requires section_code": "{0} требует section_code",
  "{0} requires group_code": "{0} требует group_code",
  "{0} requires operation_code": "{0} требует operation_code",
  "Unknown action type: {0}": "Неизвестный тип действия: {0}",
  "Action references unknown section":
    "Действие ссылается на неизвестный участок",
  "Action references unknown section_code":
    "Действие ссылается на неизвестный section_code",

  // === excel_import / plan_import_service ===
  "Unsupported Excel file extension: {0}":
    "Неподдерживаемое расширение Excel-файла: {0}",
  "Sheet index {0} not found": "Лист с индексом {0} не найден",
  "Workbook sheet is empty": "Лист книги пуст",
  "row_selection must not be empty":
    "row_selection не должен быть пустым",
  "row_selection has an empty segment":
    "В row_selection есть пустой сегмент",
  "Invalid row range '{0}'": "Некорректный диапазон строк «{0}»",
  "Row numbers must be positive in '{0}'":
    "Номера строк должны быть положительными в «{0}»",
  "Invalid row range '{0}': end is less than start":
    "Некорректный диапазон строк «{0}»: конец меньше начала",
  "Invalid row number '{0}'": "Некорректный номер строки «{0}»",
  "Row number must be positive: '{0}'":
    "Номер строки должен быть положительным: «{0}»",
  "Could not determine required headers from mapping":
    "Не удалось определить обязательные колонки из mapping",
  "Required columns are missing: {0}":
    "Отсутствуют обязательные колонки: {0}",
  "No steps/stages added for route {0}. Built route has {1} steps.":
    "Для маршрута «{0}» не добавлено ни одного этапа. Построенный маршрут содержит {1} шагов.",
  "Route {0} created without stages":
    "Маршрут «{0}» создан без этапов",

  // === backup / errors (уже частично на русском; оставлено на случай если придёт английский от обёрток) ===
  "PostgreSQL client tools недоступны, а контейнер {0} не запущен.":
    "PostgreSQL-утилиты недоступны, а контейнер {0} не запущен.",
};

/**
 * Нормализует строку с динамическими значениями в шаблон с плейсхолдерами `{0}`, `{1}`...
 * чтобы можно было искать в словаре по шаблону.
 *
 * Примеры:
 *   "Position 5 with status 'draft' cannot be approved"
 *     -> "Position {0} with status '{1}' cannot be approved"
 *   "Some positions not found or belong to a different plan"
 *     -> "Some positions not found or belong to a different plan"
 *   "Return quantity (1.5) exceeds available for return (2.0)"
 *     -> "Return quantity ({0}) exceeds available for return ({1})"
 */
function toTemplate(input: string): string {
  let out = input;
  // Числа (целые и дробные)
  out = out.replace(/-?\d+(?:[.,]\d+)?/g, "{N}");
  // Содержимое в кавычках
  out = out.replace(/'([^']*)'/g, "'{N}'");
  // Теперь заменим все {N} на инкрементные {0}, {1}, ...
  let counter = 0;
  out = out.replace(/\{N\}/g, () => `{${counter++}}`);
  return out;
}

/**
 * Переводит серверное сообщение на русский.
 * Если перевода нет — возвращает оригинал.
 */
export function translateError(message: string | null | undefined): string {
  if (!message) return message ?? "";
  const trimmed = message.trim();
  if (!trimmed) return message;

  // 1) Точное совпадение
  const exact = DICT[trimmed];
  if (exact !== undefined) return exact;

  // 2) Шаблон по динамическим значениям
  const templated = toTemplate(trimmed);
  const tplMatch = DICT[templated];
  if (tplMatch !== undefined) {
    // Подставим обратно динамические значения
    const values: string[] = [];
    let m = trimmed;
    m = m.replace(/-?\d+(?:[.,]\d+)?/g, (v) => {
      values.push(v);
      return `\u0000${values.length - 1}\u0000`;
    });
    m = m.replace(/'([^']*)'/g, (_full, v: string) => {
      values.push(v);
      return `'\u0000${values.length - 1}\u0000'`;
    });
    return tplMatch.replace(/\{(\d+)\}/g, (_full, idx: string) => {
      const i = Number(idx);
      return values[i] ?? "";
    });
  }

  return message;
}
