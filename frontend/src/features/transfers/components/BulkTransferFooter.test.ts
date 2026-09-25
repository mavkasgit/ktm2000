import { describe, expect, it } from "vitest";
import { resolveDefaultExecutorId } from "./BulkTransferFooter";

describe("resolveDefaultExecutorId", () => {
  it("uses the current user id for a regular profile", () => {
    expect(resolveDefaultExecutorId({ id: 42, is_break_glass: false }, [])).toBe(42);
  });

  it("uses the service user for break-glass id zero", () => {
    const users = [
      { id: 1, username: "system", full_name: "System User", is_active: true },
      { id: 101, username: "admin", full_name: "Администратор", is_active: true },
    ];

    expect(resolveDefaultExecutorId({ id: 0, is_break_glass: true }, users)).toBe(1);
  });

  it("does not select an invalid executor before the user list loads", () => {
    expect(resolveDefaultExecutorId({ id: 0, is_break_glass: true }, undefined)).toBeNull();
  });
});
