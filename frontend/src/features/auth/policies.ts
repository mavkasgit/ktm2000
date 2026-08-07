export const POLICIES = {
  editReferences: (role?: string) =>
    role === "admin" || role === "planner" || role === "section_manager",
  editSettings: (role?: string) => role === "admin",
}
