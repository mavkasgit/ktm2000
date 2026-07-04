import { UserRole } from "./api";

export const POLICIES = {
  editReferences: (role?: UserRole) =>
    role === "admin" || role === "planner" || role === "section_manager",
  editSettings: (role?: UserRole) => role === "admin",
};
