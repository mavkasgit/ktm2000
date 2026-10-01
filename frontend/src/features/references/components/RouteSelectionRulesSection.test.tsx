import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/shared/api/routes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/routes")>()),
  listRouteSelectionRules: vi.fn(),
  listRouteRuleProfiles: vi.fn(),
}));

vi.mock("@/shared/api/sections", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/sections")>()),
  listSections: vi.fn(),
}));

vi.mock("@/shared/api/importTemplates", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/importTemplates")>()),
  listAllImportTemplates: vi.fn(),
}));

vi.mock("@/features/auth/hooks/usePermission", () => ({
  usePermission: () => ({ canEditReferences: true }),
}));

import * as RoutesAPI from "@/shared/api/routes";
import * as SectionsAPI from "@/shared/api/sections";
import * as ImportTemplatesAPI from "@/shared/api/importTemplates";
import { RouteSelectionRulesSection } from "./RouteSelectionRulesSection";

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Запросы правил: сколько раз и с каким scope/profile_id уходили. */
function ruleRequests(): Array<{ scope?: string; profile_id?: number }> {
  return vi.mocked(RoutesAPI.listRouteSelectionRules).mock.calls.map(([params]) => params ?? {});
}

function isGlobalTabActive(): boolean {
  return screen.getByRole("button", { name: "Глобальные" }).className.includes("bg-primary");
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(SectionsAPI.listSections).mockResolvedValue([]);
  vi.mocked(ImportTemplatesAPI.listAllImportTemplates).mockResolvedValue([]);
  vi.mocked(RoutesAPI.listRouteRuleProfiles).mockResolvedValue([
    { id: 1, name: "Группа А", is_active: true } as RoutesAPI.RouteRuleProfile,
  ]);
});

describe("RouteSelectionRulesSection: авто-свитч таба", () => {
  it("не уводит с «Глобальных», пока правила ещё грузятся", async () => {
    // Профили приходят раньше правил: до ответа список правил пуст, но это
    // «не загружено», а не «правил нет» (ADR-0060 п.3).
    vi.mocked(RoutesAPI.listRouteSelectionRules).mockReturnValue(new Promise<never>(() => {}));

    render(<RouteSelectionRulesSection refreshKey={0} />);

    await waitFor(() => expect(RoutesAPI.listRouteRuleProfiles).toHaveBeenCalled());
    await waitFor(() => expect(ruleRequests()).toHaveLength(1));
    await delay(50);

    expect(ruleRequests()).toHaveLength(1);
    expect(isGlobalTabActive()).toBe(true);
  });

  it("не уводит с «Глобальных», если загрузка правил упала", async () => {
    vi.mocked(RoutesAPI.listRouteSelectionRules).mockRejectedValue(new Error("boom"));

    render(<RouteSelectionRulesSection refreshKey={0} />);

    await waitFor(() => expect(ruleRequests()).toHaveLength(1));
    await delay(50);

    expect(ruleRequests()).toHaveLength(1);
    expect(isGlobalTabActive()).toBe(true);
  });

  it("уводит на первую активную группу, когда глобальных правил действительно нет", async () => {
    vi.mocked(RoutesAPI.listRouteSelectionRules).mockResolvedValue([]);

    render(<RouteSelectionRulesSection refreshKey={0} />);

    await waitFor(() =>
      expect(ruleRequests().some((params) => params.profile_id === 1 && params.scope === "profile")).toBe(true),
    );
  });
});
