import { describe, expect, it } from "vitest";
import { MAX_SORT_FIELDS, nextMultiSortConfigs } from "./multiSort";

type Field = "id" | "name" | "status" | "extra";

describe("nextMultiSortConfigs", () => {
  it("adds new field as desc with next priority", () => {
    const next = nextMultiSortConfigs<Field>([{ field: "id", order: "asc" }], "name");
    expect(next).toEqual([
      { field: "id", order: "asc" },
      { field: "name", order: "desc" },
    ]);
  });

  it("cycles desc to asc", () => {
    const next = nextMultiSortConfigs<Field>([{ field: "name", order: "desc" }], "name");
    expect(next).toEqual([{ field: "name", order: "asc" }]);
  });

  it("removes field after asc", () => {
    const next = nextMultiSortConfigs<Field>(
      [
        { field: "id", order: "asc" },
        { field: "name", order: "asc" },
      ],
      "name",
    );
    expect(next).toEqual([{ field: "id", order: "asc" }]);
  });

  it("does not alter priority/order of other fields", () => {
    const next = nextMultiSortConfigs<Field>(
      [
        { field: "id", order: "desc" },
        { field: "status", order: "asc" },
      ],
      "id",
    );
    expect(next).toEqual([
      { field: "id", order: "asc" },
      { field: "status", order: "asc" },
    ]);
  });

  it("накопление до предела идёт обычным порядком", () => {
    const first = nextMultiSortConfigs<Field>([], "id");
    const second = nextMultiSortConfigs<Field>(first, "name");
    const third = nextMultiSortConfigs<Field>(second, "status");

    expect(third).toEqual([
      { field: "id", order: "desc" },
      { field: "name", order: "desc" },
      { field: "status", order: "desc" },
    ]);
    expect(third).toHaveLength(MAX_SORT_FIELDS);
  });

  it("при добавлении четвёртой колонки вытесняется самая старая", () => {
    const three = [
      { field: "id" as Field, order: "desc" as const },
      { field: "name" as Field, order: "desc" as const },
      { field: "status" as Field, order: "desc" as const },
    ];

    const fourth = nextMultiSortConfigs<Field>(three, "extra");

    // Приоритет 1 («id») снят, чтобы оператор не упирался в предел.
    expect(fourth).toEqual([
      { field: "name", order: "desc" },
      { field: "status", order: "desc" },
      { field: "extra", order: "desc" },
    ]);
    expect(fourth).toHaveLength(MAX_SORT_FIELDS);
  });

  it("переключение направления у уже выбранной колонки не снимает её из набора", () => {
    const three = [
      { field: "id" as Field, order: "desc" as const },
      { field: "name" as Field, order: "desc" as const },
      { field: "status" as Field, order: "desc" as const },
    ];

    // Клик по «status» при заполненном наборе меняет направление, а не вытесняет.
    const toggled = nextMultiSortConfigs<Field>(three, "status");

    expect(toggled).toEqual([
      { field: "id", order: "desc" },
      { field: "name", order: "desc" },
      { field: "status", order: "asc" },
    ]);
  });

  it("снятие направления освобождает место для следующей колонки", () => {
    const three = [
      { field: "id" as Field, order: "desc" as const },
      { field: "name" as Field, order: "desc" as const },
      { field: "status" as Field, order: "desc" as const },
    ];

    // 1-й клик по «name»: desc → asc (колонка остаётся в наборе).
    const ascending = nextMultiSortConfigs<Field>(three, "name");
    expect(ascending).toHaveLength(3);

    // 2-й клик по «name»: asc → снята, освободилось место.
    const two = nextMultiSortConfigs<Field>(ascending, "name");
    expect(two).toEqual([
      { field: "id", order: "desc" },
      { field: "status", order: "desc" },
    ]);

    // Место занято, четвёртая колонка добавляется без вытеснения.
    const next = nextMultiSortConfigs<Field>(two, "extra");
    expect(next).toEqual([
      { field: "id", order: "desc" },
      { field: "status", order: "desc" },
      { field: "extra", order: "desc" },
    ]);
  });
});
