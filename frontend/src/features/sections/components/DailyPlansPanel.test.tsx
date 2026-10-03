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

describe("DailyPlansPanel: выбор не переставляет список", () => {
  it("порядок карточек не меняется, выбранная помечается на месте", () => {
    const plans = backendOrder(planSeries(3));
    const { container, rerender } = render(
      <DailyPlansPanel
        plans={plans}
        selectedPlanIds={new Set()}
        onSelectPlan={vi.fn()}
        onTogglePlan={vi.fn()}
        onClearPlans={vi.fn()}
      />,
    );
    const before = visibleTitles(container);
    expect(before).toEqual([3, 2, 1].map((n) => `План №${n} · 26.09.2026`));

    rerender(
      <DailyPlansPanel
        plans={plans}
        selectedPlanIds={new Set([1])}
        onSelectPlan={vi.fn()}
        onTogglePlan={vi.fn()}
        onClearPlans={vi.fn()}
      />,
    );

    expect(visibleTitles(container), "выбор не переставляет карточки").toEqual(before);
    expect(container.textContent, "выбранная помечена на месте").toContain("· выбрано");
    expect(container.textContent, "ярлык собран в полосе «Выбрано»").toContain("Выбрано (1)");
  });

  it("крестик ярлыка снимает выбор именно с этого плана", () => {
    const onTogglePlan = vi.fn();
    // Ярлыки идут в порядке дат: id 2, затем id 1.
    render(
      <DailyPlansPanel
        plans={backendOrder(planSeries(3))}
        selectedPlanIds={new Set([1, 2])}
        onSelectPlan={vi.fn()}
        onTogglePlan={onTogglePlan}
        onClearPlans={vi.fn()}
      />,
    );

    expect(screen.getByText("Выбрано (2)")).toBeTruthy();
    const undoChips = screen.getAllByRole("button", { name: "Убрать план из выбранных" });
    expect(undoChips).toHaveLength(2);

    fireEvent.click(undoChips[0]);

    expect(onTogglePlan).toHaveBeenCalledTimes(1);
    expect(onTogglePlan).toHaveBeenCalledWith(2);
  });

  it("поиск отсеивает карточку выбранного плана, но ярлык остаётся", () => {
    // Доска показывает задания выбранного плана и при отсеянной поиском
    // карточке — ярлык в полосе это и обеспечивает.
    const { container } = renderPanel(
      [
        makePlan({ id: 1, plan_date: "2026-10-15", created_at: "2026-10-15T08:00:00" }),
        makePlan({ id: 2, plan_date: "2026-10-26", created_at: "2026-10-26T08:00:00" }),
      ],
      [1],
    );
    search("26");

    expect(visibleTitles(container)).toEqual(["План №1 · 26.10.2026"]);
    expect(container.textContent).toContain("Выбрано (1)");
    expect(container.textContent, "ярлык отсеянного выбранного плана на месте").toContain(
      "15.10.2026",
    );
  });

  it("«Все задания участка» и ✕ очищают выбор целиком", () => {
    const onClearPlans = vi.fn();
    render(
      <DailyPlansPanel
        plans={backendOrder(planSeries(3))}
        selectedPlanIds={new Set([1])}
        onSelectPlan={vi.fn()}
        onTogglePlan={vi.fn()}
        onClearPlans={onClearPlans}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Все задания участка" }));
    expect(onClearPlans).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Выключить все планы" }));
    expect(onClearPlans).toHaveBeenCalledTimes(2);
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
  it("без поиска показывает 8 из 12, раскрытие показывает остаток с настоящими номерами", () => {
    const { container } = renderPanel(backendOrder(planSeries(12)));

    expect(visibleTitles(container)).toEqual(
      [12, 11, 10, 9, 8, 7, 6, 5].map((n) => `План №${n} · 26.09.2026`),
    );
    const showMore = screen.getByRole("button", { name: "Показать ещё" });
    fireEvent.click(showMore);

    expect(visibleTitles(container)).toEqual(
      Array.from({ length: 12 }, (_, index) => `План №${12 - index} · 26.09.2026`),
    );
    expect(screen.queryByRole("button", { name: "Показать ещё" })).toBeNull();
  });

  it("восемь планов помещаются в панель целиком, без «Показать ещё»", () => {
    const { container } = renderPanel(backendOrder(planSeries(8)));

    // Потолок выведен из высоты панели: восемь карточек — это ровно то, что
    // влезает вместе с заголовком, поиском и кнопкой. Девятый план уже
    // требовал бы прокрутки внутри списка.
    expect(visibleTitles(container)).toHaveLength(8);
    expect(screen.queryByRole("button", { name: "Показать ещё" })).toBeNull();
  });


  it("кнопки нет, когда все планы помещаются в потолок", () => {
    renderPanel(backendOrder(planSeries(4)));

    expect(screen.queryByRole("button", { name: "Показать ещё" })).toBeNull();
  });

  it("поиск возвращает к потолку 20, а его сброс — к 8", () => {
    const { container } = renderPanel(backendOrder(planSeries(25)));
    expect(visibleTitles(container)).toHaveLength(8);

    fireEvent.click(screen.getByRole("button", { name: "Показать ещё" }));
    expect(visibleTitles(container)).toHaveLength(25);
    expect(screen.queryByRole("button", { name: "Показать ещё" })).toBeNull();

    search("09");
    expect(visibleTitles(container)).toHaveLength(20);
    expect(screen.getByRole("button", { name: "Показать ещё" })).toBeTruthy();

    search("");
    expect(visibleTitles(container)).toHaveLength(8);
  });

  it("выбранный план за потолком виден ярлыком, а не карточкой", () => {
    const { container } = renderPanel(backendOrder(planSeries(25)), [1]);
    const text = container.textContent ?? "";

    expect(text).toContain("Выбрано (1)");
    expect(text, "ярлык выбранного плана на месте").toContain("План №1 · 26.09.2026");
    expect(visibleTitles(container)).toHaveLength(8);
    expect(visibleTitles(container), "карточка не вытесняет соседей наверх").not.toContain(
      "План №1 · 26.09.2026",
    );
  });
});

describe("DailyPlansPanel: создание плана", () => {
  it("«Создать план» снимает фильтр выбранных планов", () => {
    const onClearPlans = vi.fn();
    render(
      <DailyPlansPanel
        plans={backendOrder(planSeries(3))}
        selectedPlanIds={new Set([1])}
        onSelectPlan={vi.fn()}
        onTogglePlan={vi.fn()}
        onClearPlans={onClearPlans}
        onCreatePlan={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Создать план" }));

    // Иначе доска осталась бы на составе прежнего плана, а кандидатов нового
    // не показала: режим создания выбирает задания участка.
    expect(onClearPlans).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("textbox", { name: "Дата плана" })).toBeTruthy();
  });
});
