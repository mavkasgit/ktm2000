/**
 * Массовый ввод факта прямо в таблице доски (#283).
 *
 * Контракт, который защищают тесты: поля «Годные»/«Брак» появляются только у
 * выделенной строки; ввод уходит в черновик, привязанный к задаче; групповое
 * поле раскладывает количество последовательно по строкам, а избыток остаётся
 * в последней строке и помечается «сверх плана»; недопустимый символ не
 * подставляется и его причина уходит наружу (её печатает футер).
 */

import { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { SectionBoardTask } from "@/shared/api/shopfloor";
import type { PageLimitOption } from "@/shared/hooks/usePaginatedTableQuery";
import { useBulkSelection } from "@/shared/bulk";
import type { GroupingProfile } from "../lib/groupingProfiles";
import type { BulkDraft } from "../lib/bulkDraft";
import { SectionTasksBoard } from "./SectionTasksBoard";

const PROFILE: GroupingProfile = {
  id: "sku",
  name: "Артикул + размер",
  criteria: ["productSku"],
};

function makeTask(overrides: Partial<SectionBoardTask> = {}): SectionBoardTask {
  return {
    id: 1,
    product_id: 1,
    product_sku: "SKU-A",
    section_plan_line_id: 1,
    plan_position_id: 1,
    route_step_id: 1,
    sequence: 1,
    operation_code: "op",
    operation_name: "Операция",
    is_significant: true,
    planned_quantity: "10",
    status: "in_progress",
    cache: {
      available_quantity: "0",
      issued_quantity: "10",
      completed_quantity: "0",
      transferred_quantity: "0",
      received_quantity: "0",
      rejected_quantity: "0",
      remaining_quantity: "10",
    },
    previous_stage: null,
    next_task_id: null,
    next_task_status: null,
    next_operation_name: null,
    source_ref: null,
    source_payload: {},
    source_fingerprint: null,
    input_sku: "SKU-A",
    output_sku: "SKU-A",
    display_sku: "SKU-A",
    route_history: [],
    route_history_after: [],
    route_history_full: [],
    route_history_after_full: [],
    operation_codes: [],
    operation_names: [],
    ...overrides,
  };
}

function Harness({ tasks }: { tasks: SectionBoardTask[] }) {
  const [draft, setDraft] = useState<BulkDraft>({});
  const [bulkMode, setBulkMode] = useState(true);
  const bulkSelection = useBulkSelection<number>();
  return (
    <>
      <button type="button" onClick={() => setBulkMode((prev) => !prev)}>
        {bulkMode ? "выйти из массового режима" : "включить массовый режим"}
      </button>
      <SectionTasksBoard
        tasks={tasks}
        total={tasks.length}
        isLoading={false}
        mode={{ active: true, waiting: true, completed: false }}
        onModeChange={vi.fn()}
        onAction={vi.fn()}
        profile={PROFILE}
        bulkMode={bulkMode}
        bulkSelection={bulkMode ? bulkSelection : undefined}
        bulkDraft={draft}
        onBulkDraftChange={setDraft}
        onVisibleTaskIdsChange={vi.fn()}
        page={1}
        setPage={vi.fn()}
        limit={50 as PageLimitOption}
        setLimit={vi.fn()}
        totalPages={1}
        rangeLabel=""
        onServerQueryChange={vi.fn()}
      />
      <output data-testid="draft">{JSON.stringify(draft)}</output>
    </>
  );
}

/**
 * Десктопная таблица доски. Запросы идут только по ней: узкий экран рисуется
 * вторым деревом (карточки) в том же DOM, и одинаковые подписи полей были бы
 * неразличимы.
 */
function desktop(): HTMLElement {
  const table = document.querySelector("table");
  if (!table) throw new Error("таблица доски не найдена");
  return table as HTMLElement;
}

/** Строка задания по артикулу (десктопная таблица). */
function taskRow(sku: string): HTMLElement {
  const row = within(desktop()).getAllByText(sku).map((node) => node.closest("tr")).find(Boolean);
  if (!row) throw new Error(`строка ${sku} не найдена`);
  return row as HTMLElement;
}

describe("SectionTasksBoard: массовый ввод факта", () => {
  it("поля открываются только у выделенной строки", () => {
    render(<Harness tasks={[makeTask({ id: 1, product_sku: "SKU-A" }), makeTask({ id: 2, product_sku: "SKU-B" })]} />);

    expect(within(desktop()).queryByLabelText("SKU-A: годные")).toBeNull();

    fireEvent.click(taskRow("SKU-A"));

    expect(within(desktop()).getByLabelText("SKU-A: годные")).toBeTruthy();
    expect(within(desktop()).queryByLabelText("SKU-B: годные")).toBeNull();
  });

  it("введённое уходит в черновик и плейсхолдер несёт записанный факт", () => {
    render(
      <Harness
        tasks={[
          makeTask({
            id: 1,
            product_sku: "SKU-A",
            cache: { ...makeTask().cache, issued_quantity: "10", completed_quantity: "3" },
          }),
        ]}
      />,
    );
    fireEvent.click(taskRow("SKU-A"));

    const good = within(desktop()).getByLabelText("SKU-A: годные");
    // Плейсхолдер — сам записанный факт, без слова: «сейчас 3» не влезало
    // в поле шириной 38px. Смысл подписи несёт title.
    expect(good.getAttribute("placeholder")).toBe("3");
    expect(good.getAttribute("title")).toBe("Записано: 3");

    fireEvent.change(good, { target: { value: "4" } });

    expect(screen.getByTestId("draft").textContent).toBe('{"1":{"good":"4","defect":""}}');
  });

  it("недопустимый символ не подставляется, причина видна у самого поля", () => {
    render(<Harness tasks={[makeTask({ id: 1, product_sku: "SKU-A" })]} />);
    fireEvent.click(taskRow("SKU-A"));

    const good = within(desktop()).getByLabelText("SKU-A: годные");
    expect(screen.queryAllByText(/Запятая и точка/)).toHaveLength(0);

    fireEvent.change(good, { target: { value: "1" } });
    fireEvent.change(good, { target: { value: "1,5" } });

    // Запятая не подставляется: поле остаётся с прежним значением, а причина
    // читается у самого поля — подсказкой, раскрытой без наведения (в футер
    // оператор не смотрит, а под полем в 32-пиксельной строке места нет).
    expect(screen.getByTestId("draft").textContent).toBe('{"1":{"good":"1","defect":""}}');
    // Radix рисует содержимое подсказки дважды: видимое и скрытую копию
    // для чтения с экрана.
    expect(screen.getAllByText(/Запятая и точка/).length).toBeGreaterThan(0);
    expect(good.getAttribute("aria-invalid")).toBe("true");

    // Допустимый ввод снимает причину.
    fireEvent.change(good, { target: { value: "15" } });
    expect(screen.queryAllByText(/Запятая и точка/)).toHaveLength(0);
  });

  it("включение массового режима не раскрывает группы: строки открывает выбор группы", () => {
    render(
      <Harness
        tasks={[
          makeTask({ id: 1, product_sku: "SKU-A", cache: { ...makeTask().cache, issued_quantity: "10" } }),
          makeTask({ id: 2, product_sku: "SKU-A", cache: { ...makeTask().cache, issued_quantity: "5" } }),
        ]}
      />,
    );

    // Сначала выходим из режима: группа из двух заданий свёрнута, строк нет.
    fireEvent.click(screen.getByRole("button", { name: "выйти из массового режима" }));
    expect(within(desktop()).queryAllByText("SKU-A")).toHaveLength(1);

    // Вход в режим ничего не раскрывает: раскрытие — следствие выбора, а не
    // входа в групповые операции.
    fireEvent.click(screen.getByRole("button", { name: "включить массовый режим" }));
    expect(within(desktop()).getAllByText("SKU-A")).toHaveLength(1);
    expect(within(desktop()).queryByLabelText("SKU-A: годные")).toBeNull();

    // Выбор группы целиком (клик по шапке) раскрывает её строки — и сразу
    // выделяет все: поля ввода открыты у каждой.
    fireEvent.click(within(desktop()).getByLabelText("SKU-A: годные группы").closest("tr")!);
    expect(within(desktop()).getAllByText("SKU-A").length).toBeGreaterThan(1);
    expect(within(desktop()).getAllByLabelText("SKU-A: годные")).toHaveLength(2);
  });

  it("повторный клик по лишней строке снимает её выбор, а последняя снимает выбор группы", () => {
    render(
      <Harness
        tasks={[
          makeTask({ id: 1, product_sku: "SKU-A", cache: { ...makeTask().cache, issued_quantity: "10" } }),
          makeTask({ id: 2, product_sku: "SKU-A", cache: { ...makeTask().cache, issued_quantity: "5" } }),
        ]}
      />,
    );

    fireEvent.click(within(desktop()).getByLabelText("SKU-A: годные группы").closest("tr")!);
    const rows = within(desktop()).getAllByLabelText("SKU-A: годные").map((input) => input.closest("tr")!);
    expect(rows).toHaveLength(2);

    // Сняли выбор с одной строки — группа осталась раскрытой: в ней есть выбор.
    fireEvent.click(rows[0]);
    expect(within(desktop()).getAllByLabelText("SKU-A: годные")).toHaveLength(1);

    // Сняли с последней — раскрывать нечего, группа вернулась к свёрнутому виду.
    fireEvent.click(rows[1]);
    expect(within(desktop()).queryAllByText("SKU-A")).toHaveLength(1);
  });

  it("групповое поле раскладывает количество по строкам сверху вниз", () => {
    render(
      <Harness
        tasks={[
          makeTask({ id: 1, product_sku: "SKU-A", cache: { ...makeTask().cache, issued_quantity: "10" } }),
          makeTask({ id: 2, product_sku: "SKU-A", cache: { ...makeTask().cache, issued_quantity: "5" } }),
        ]}
      />,
    );

    const groupInput = within(desktop()).getByLabelText("SKU-A: годные группы");
    fireEvent.change(groupInput, { target: { value: "12" } });

    const rows = within(desktop()).getAllByLabelText("SKU-A: годные") as HTMLInputElement[];
    expect(rows.map((input) => input.value)).toEqual(["10", "2"]);
  });

  it("избыток не теряется: остаётся в последней строке и помечен", () => {
    render(
      <Harness
        tasks={[
          makeTask({ id: 1, product_sku: "SKU-A", cache: { ...makeTask().cache, issued_quantity: "10" } }),
          makeTask({ id: 2, product_sku: "SKU-A", cache: { ...makeTask().cache, issued_quantity: "5" } }),
        ]}
      />,
    );

    fireEvent.change(within(desktop()).getByLabelText("SKU-A: годные группы"), { target: { value: "18" } });

    const rows = within(desktop()).getAllByLabelText("SKU-A: годные") as HTMLInputElement[];
    expect(rows.map((input) => input.value)).toEqual(["10", "8"]);
    // Введённое сверх потолка строки помечено без наведения: у последней
    // строки есть знак с подписью «Сверх плана».
    const lastRow = rows[1].closest("tr") as HTMLElement;
    expect(within(lastRow).getAllByTitle(/Сверх плана/).length).toBeGreaterThan(0);
  });
});

describe("SectionTasksBoard: два режима ввода факта", () => {
  const withRecorded = (id: number, completed: string, issued = "1000") =>
    makeTask({
      id,
      product_sku: "SKU-A",
      cache: { ...makeTask().cache, issued_quantity: issued, completed_quantity: completed },
    });

  it("«+100» добавляет, «500» ставит факт — режим несёт ведущий «+»", () => {
    render(<Harness tasks={[withRecorded(1, "400")]} />);
    fireEvent.click(taskRow("SKU-A"));

    const good = within(desktop()).getByLabelText("SKU-A: годные");
    fireEvent.change(good, { target: { value: "+100" } });
    expect(screen.getByTestId("draft").textContent).toBe('{"1":{"good":"+100","defect":""}}');

    fireEvent.change(good, { target: { value: "500" } });
    expect(screen.getByTestId("draft").textContent).toBe('{"1":{"good":"500","defect":""}}');
  });

  it("факт меньше записанного: значение остаётся в поле, причина — у поля", () => {
    render(<Harness tasks={[withRecorded(1, "400")]} />);
    fireEvent.click(taskRow("SKU-A"));

    const good = within(desktop()).getByLabelText("SKU-A: годные");
    fireEvent.change(good, { target: { value: "300" } });

    // Значение остаётся в поле: цифру надо добрать посимвольно до допустимой.
    expect(screen.getByTestId("draft").textContent).toBe('{"1":{"good":"300","defect":""}}');
    expect(screen.getAllByText(/можно только увеличить/).length).toBeGreaterThan(0);
    expect(good.getAttribute("aria-invalid")).toBe("true");

    fireEvent.change(good, { target: { value: "500" } });
    expect(screen.queryAllByText(/можно только увеличить/)).toHaveLength(0);
    expect(good.getAttribute("aria-invalid")).toBe("false");
  });

  it("цель в поле группы: строки получают цели, поле показывает их сумму", () => {
    render(
      <Harness
        tasks={[
          makeTask({ id: 1, product_sku: "SKU-A", cache: { ...makeTask().cache, issued_quantity: "100", completed_quantity: "40" } }),
          makeTask({ id: 2, product_sku: "SKU-A", cache: { ...makeTask().cache, issued_quantity: "100", completed_quantity: "0" } }),
        ]}
      />,
    );

    fireEvent.change(within(desktop()).getByLabelText("SKU-A: годные группы"), {
      target: { value: "60" },
    });

    expect(screen.getByTestId("draft").textContent).toBe('{"1":{"good":"60","defect":""}}');
    expect(
      (within(desktop()).getByLabelText("SKU-A: годные группы") as HTMLInputElement).value,
    ).toBe("60");
  });

  it("набранное в поле группы остаётся, пока цель не разложена", () => {
    render(
      <Harness
        tasks={[
          makeTask({ id: 1, product_sku: "SKU-A", cache: { ...makeTask().cache, issued_quantity: "100", completed_quantity: "40" } }),
          makeTask({ id: 2, product_sku: "SKU-A", cache: { ...makeTask().cache, issued_quantity: "100", completed_quantity: "0" } }),
        ]}
      />,
    );

    const group = within(desktop()).getByLabelText("SKU-A: годные группы");
    fireEvent.change(group, { target: { value: "20" } });

    // Цель ниже записанного (40) не раскладывается, но набранное видно в поле
    // группы и причина названа — иначе цифру не добрать посимвольно.
    expect(screen.getByTestId("draft").textContent).toBe("{}");
    expect((within(desktop()).getByLabelText("SKU-A: годные группы") as HTMLInputElement).value).toBe("20");
    expect(screen.getAllByText(/можно только увеличить/).length).toBeGreaterThan(0);
  });

  it("«+» в поле группы не теряется при посимвольном наборе", () => {
    render(
      <Harness
        tasks={[
          makeTask({ id: 1, product_sku: "SKU-A", cache: { ...makeTask().cache, issued_quantity: "100" } }),
          makeTask({ id: 2, product_sku: "SKU-A", cache: { ...makeTask().cache, issued_quantity: "100" } }),
        ]}
      />,
    );

    const group = () => within(desktop()).getByLabelText("SKU-A: годные группы") as HTMLInputElement;
    // Оператор набирает по символу: «+», «5», «0». Промежуточный «+» — ещё не
    // ввод, но он обязан остаться в поле, иначе режим добавки не набрать.
    fireEvent.change(group(), { target: { value: "+" } });
    expect(group().value).toBe("+");
    fireEvent.change(group(), { target: { value: "+5" } });
    fireEvent.change(group(), { target: { value: "+50" } });

    expect(group().value).toBe("+50");
    expect(screen.getByTestId("draft").textContent).toBe('{"1":{"good":"+50","defect":""}}');
  });
});

/**
 * Отбор строки — не действие над заданием: «ожидает предыдущего участка» —
 * допустимый кандидат дневного плана (в плане запрещены только терминальные
 * задания), и шапка группы такие строки выделяла всегда. Клик по одиночной
 * строке их не выделял — половина кандидатов участка оставалась недоступной.
 */
describe("SectionTasksBoard: отбор строки в статусе «ожидает предыдущего участка»", () => {
  const waitingTask = () =>
    makeTask({ id: 1, product_sku: "SKU-WAIT", status: "waiting_previous" });

  it("клик по одиночной строке выделяет её", () => {
    render(<Harness tasks={[waitingTask()]} />);
    expect(taskRow("SKU-WAIT").getAttribute("aria-selected")).toBe("false");

    fireEvent.click(taskRow("SKU-WAIT"));

    expect(taskRow("SKU-WAIT").getAttribute("aria-selected")).toBe("true");
  });

  it("клавиатура выделяет такую строку тем же правилом", () => {
    render(<Harness tasks={[waitingTask()]} />);

    fireEvent.keyDown(taskRow("SKU-WAIT"), { key: "Enter" });

    expect(taskRow("SKU-WAIT").getAttribute("aria-selected")).toBe("true");
  });
});
