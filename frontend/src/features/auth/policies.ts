export const POLICIES = {
  editReferences: (role?: string) =>
    role === "admin" || role === "planner" || role === "section_manager",
  /** Принудительное удаление импорта поверх живых данных — только админу. */
  forceDeleteImport: (role?: string) => role === "admin",
  editSettings: (role?: string) => role === "admin",
}
