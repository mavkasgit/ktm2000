export const POLICIES = {
  editReferences: (role?: string) =>
    role === "admin" || role === "planner" || role === "section_manager",
  /** Принудительное удаление импорта поверх живых данных — только админу. */
  forceDeleteImport: (role?: string) => role === "admin",
  /**
   * Откат батча импорта остатков — только админу (ADR-0052 п.6).
   * Зеркалится серверным гейтом по типу действия в `reversal/api.py`,
   * поэтому это подсказка интерфейса, а не единственная защита.
   */
  rollbackImport: (role?: string) => role === "admin",
  editSettings: (role?: string) => role === "admin",
  /**
   * Мутации плана — зеркало `PLAN_WRITER_ROLES` (backend, ADR-0057): разделы
   * `/planning` и `/execution`, где нарисованы эти кнопки. Массовые действия
   * держат тот же набор, что одиночные (issue #235).
   */
  editPlan: (role?: string) =>
    role === "admin" || role === "planner" || role === "section_manager",
  /**
   * Создание батча импорта плана из мастера на `/planning` — зеркало
   * `PLAN_OWNER_ROLES` (backend, ADR-0057).
   */
  createPlanImport: (role?: string) => role === "admin" || role === "planner",
  /**
   * Коммит и снос батча импорта плана (`apply`/`rollback`/`discard`/`delete`) —
   * зеркало admin-гейта тех же ручек (ADR-0057, по образцу ADR-0052 п.6).
   */
  managePlanImport: (role?: string) => role === "admin",
}
