import { describe, expect, it } from "vitest";
import { nextMultiSortConfigs } from "./multiSort";

type Field = "id" | "name" | "status";

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
});

