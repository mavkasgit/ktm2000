import { describe, expect, it } from "vitest";
import { nextMultiSortConfigs } from "./multiSort";

type Field = "id" | "name" | "status";

describe("nextMultiSortConfigs", () => {
  it("adds new field as asc with next priority", () => {
    const next = nextMultiSortConfigs<Field>([{ field: "id", order: "asc" }], "name");
    expect(next).toEqual([
      { field: "id", order: "asc" },
      { field: "name", order: "asc" },
    ]);
  });

  it("cycles asc to desc", () => {
    const next = nextMultiSortConfigs<Field>([{ field: "name", order: "asc" }], "name");
    expect(next).toEqual([{ field: "name", order: "desc" }]);
  });

  it("removes field after desc", () => {
    const next = nextMultiSortConfigs<Field>(
      [
        { field: "id", order: "asc" },
        { field: "name", order: "desc" },
      ],
      "name",
    );
    expect(next).toEqual([{ field: "id", order: "asc" }]);
  });

  it("does not alter priority/order of other fields", () => {
    const next = nextMultiSortConfigs<Field>(
      [
        { field: "id", order: "asc" },
        { field: "status", order: "desc" },
      ],
      "id",
    );
    expect(next).toEqual([
      { field: "id", order: "desc" },
      { field: "status", order: "desc" },
    ]);
  });
});

