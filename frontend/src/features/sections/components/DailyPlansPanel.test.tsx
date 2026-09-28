import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { DailyPlanSummary } from "@/shared/api/shopfloor";
import { DailyPlansPanel } from "./DailyPlansPanel";

function makePlan(overrides: Partial<DailyPlanSummary> = {}): DailyPlanSummary {
  return {
    id: 1,
    section_id: 7,
    plan_date: "2026-09-26",
    created_at: "2026-09-26T08:00:00",
    created_by: 3,
    item_count: 4,
    progress_percent: 50,
    ...overrides,
  };
}

/** count планов одной даты: план №k создан на k-й минуте после 08:00. */
function planSeries(count: number, planDate = "2026-09-26"): DailyPlanSummary[] {
  return Array.from({ length: count }, (_, index) =>
    makePlan({
      id: index + 1,
      plan_date: planDate,
      created_at: `${planDate}T08:${String(index).padStart(2, "0")}:00`,
    }),
  );
}

/** Порядок бэкенда: `plan_date DESC, created_at DESC` — свежие сверху. */
function backendOrder(plans: DailyPlanSummary[]): DailyPlanSummary[] {
  return [...plans].reverse();
}

/** Заголовки видимых карточек: «План №N · дд.мм.гггг». */
function visibleTitles(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll("[data-plan-select] span"))
    .map((node) => node.textContent ?? "")
    .filter((text) => text.startsWith("План №"));
}

function renderPanel(plans: DailyPlanSummary[], selectedPlanIds: number[] = []) {
  return render(
    <DailyPlansPanel
      plans={plans}
      selectedPlanIds={new Set(selectedPlanIds)}
      onSelectPlan={vi.fn()}
      onTogglePlan={vi.fn()}
      onClearPlans={vi.fn()}
    />,
  );
}

function search(value: string): void {
  fireEvent.change(screen.getByLabelText("Поиск дневных планов"), { target: { value } });
}

describe("DailyPlansPanel: порядок блоков", () => {
  it("ставит «Выбрано» сверху, обычные ниже, «Не найдено среди выбранных» в хвост", () => {
    // 26.09 выбран и подходит под «26», 26.10 обычный и подходит,
    // 15.10 выбран, но под «26» не подходит.
    const { container } = renderPanel(
      [
        makePlan({ id: 1, plan_date: "2026-09-26", created_at: "2026-09-26T08:00:00" }),
        makePlan({ id: 2, plan_date: "2026-10-26", created_at: "2026-10-26T08:00:00" }),
        makePlan({ id: 3, plan_date: "2026-10-15", created_at: "2026-10-15T08:00:00" }),
      ],
      [1, 3],
    );
    search("26");

    const text = container.textContent ?? "";
    const selectedTitleAt = text.indexOf("Выбрано (1)");
    const selectedCardAt = text.indexOf("26.09.2026");
    const otherCardAt = text.indexOf("26.10.2026");
    const outOfSearchTitleAt = text.indexOf("Не найдено среди выбранных (1)");
    const outOfSearchCardAt = text.indexOf("15.10.2026");

    expect(selectedTitleAt).toBeGreaterThan(-1);
    expect(selectedCardAt).toBeGreaterThan(selectedTitleAt);
    expect(otherCardAt).toBeGreaterThan(selectedCardAt);
    expect(outOfSearchTitleAt).toBeGreaterThan(otherCardAt);
    expect(outOfSearchCardAt).toBeGreaterThan(outOfSearchTitleAt);
  });

  it("клик по чекбоксу карточки сообщает id именно этой карточки", () => {
    const onTogglePlan = vi.fn();
    const plans = backendOrder(planSeries(3));
    const { container } = render(
      <DailyPlansPanel
        plans={plans}
        selectedPlanIds={new Set()}
        onSelectPlan={vi.fn()}
        onTogglePlan={onTogglePlan}
        onClearPlans={vi.fn()}
      />,
    );

    // Первая в выдаче карточка — самый свежий план, id 3.
    expect(visibleTitles(container)[0]).toBe("План №3 · 26.09.2026");
    fireEvent.click(container.querySelectorAll('[role="checkbox"]')[0]);

    expect(onTogglePlan).toHaveBeenCalledTimes(1);
    expect(onTogglePlan).toHaveBeenCalledWith(3);
  });
});

describe("DailyPlansPanel: потолок и «Показать ещё»", () => {
  it("без поиска показывает 10 из 12, раскрытие показывает остаток с настоящими номерами", () => {
    const { container } = renderPanel(backendOrder(planSeries(12)));

    expect(visibleTitles(container)).toEqual(
      [12, 11, 10, 9, 8, 7, 6, 5, 4, 3].map((n) => `План №${n} · 26.09.2026`),
    );
    const showMore = screen.getByRole("button", { name: "Показать ещё" });
    fireEvent.click(showMore);

    expect(visibleTitles(container)).toEqual(
      Array.from({ length: 12 }, (_, index) => `План №${12 - index} · 26.09.2026`),
    );
    expect(screen.queryByRole("button", { name: "Показать ещё" })).toBeNull();
  });

  it("кнопки нет, когда все планы помещаются в потолок", () => {
    renderPanel(backendOrder(planSeries(4)));

    expect(screen.queryByRole("button", { name: "Показать ещё" })).toBeNull();
  });

  it("поиск возвращает к потолку 20, а его сброс — к 10", () => {
    const { container } = renderPanel(backendOrder(planSeries(25)));
    expect(visibleTitles(container)).toHaveLength(10);

    fireEvent.click(screen.getByRole("button", { name: "Показать ещё" }));
    expect(visibleTitles(container)).toHaveLength(25);
    expect(screen.queryByRole("button", { name: "Показать ещё" })).toBeNull();

    search("09");
    expect(visibleTitles(container)).toHaveLength(20);
    expect(screen.getByRole("button", { name: "Показать ещё" })).toBeTruthy();

    search("");
    expect(visibleTitles(container)).toHaveLength(10);
  });

  it("выбранный план за пределом потолка остаётся на экране", () => {
    const { container } = renderPanel(backendOrder(planSeries(25)), [1]);
    const text = container.textContent ?? "";

    expect(text).toContain("Выбрано (1)");
    expect(visibleTitles(container)).toHaveLength(10);
    expect(visibleTitles(container)).toContain("План №1 · 26.09.2026");
  });
});
