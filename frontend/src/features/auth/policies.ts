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
}
