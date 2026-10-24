import { describe, expect, it } from "vitest";

import { POLICIES } from "./policies";

/**
 * План-импортные политики — зеркало серверных наборов ролей (ADR-0057):
 * `PLAN_OWNER_ROLES` = admin, planner; `PLAN_WRITER_ROLES` = admin, planner,
 * section_manager. Таблица фиксирует набор дословно: расширение политики
 * «на всякий случай» разошлось бы с бэком и стало бы подсказкой-обманкой —
 * сервер вернул бы 403 там, где фронт показывает кнопку.
 */
const PLAN_POLICIES = {
  editPlan: ["admin", "planner", "section_manager"],
  createPlanImport: ["admin", "planner"],
  managePlanImport: ["admin"],
} as const;

const ROLES = ["admin", "planner", "section_manager", "operator", "viewer", "transporter"] as const;

describe("plan policies", () => {
  for (const [policy, allowed] of Object.entries(PLAN_POLICIES)) {
    it(`${policy} пускает ровно ${allowed.join(", ")}`, () => {
      const check = POLICIES[policy as keyof typeof PLAN_POLICIES];
      for (const role of ROLES) {
        expect(check(role), `${policy}: ${role}`).toBe((allowed as readonly string[]).includes(role));
      }
    });

    it(`${policy} без роли (не залогинен) запрещает`, () => {
      expect(POLICIES[policy as keyof typeof PLAN_POLICIES](undefined)).toBe(false);
    });
  }
});
