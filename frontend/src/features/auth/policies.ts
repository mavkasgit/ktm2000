import { UserRole } from "./api";

export const POLICIES = {
  editReferences: (role?: UserRole) => role === "admin" || role === "planner",
  editSettings: (role?: UserRole) => role === "admin",
};
