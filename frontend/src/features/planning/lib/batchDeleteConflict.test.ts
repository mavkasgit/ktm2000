import { describe, expect, it } from "vitest";
import { blockerReasonLabel, parseBatchDeleteConflict } from "./batchDeleteConflict";

function axiosError(status: number, data: unknown) {
  return { response: { status, data } };
}

describe("parseBatchDeleteConflict", () => {
  it("разбирает 409 с блокерами released", () => {
    const conflict = parseBatchDeleteConflict(
      axiosError(409, {
        code: "batch_has_released_positions",
        blockers: [{ position_id: 7, reason: "released" }],
        safe_action: "delete_drafts_only",
        drafts: 2,
      }),
    );
    expect(conflict?.code).toBe("batch_has_released_positions");
    expect(conflict?.blockers).toHaveLength(1);
    expect(conflict?.drafts).toBe(2);
  });

  it("разбирает 409 с передачами", () => {
    const conflict = parseBatchDeleteConflict(
      axiosError(409, {
        code: "downstream_transfers_exist",
        blockers: [{ position_id: 9, reason: "transfer №TR-1" }],
        safe_action: "delete_drafts_only",
        drafts: 0,
      }),
    );
    expect(conflict?.code).toBe("downstream_transfers_exist");
  });

  it("игнорирует не-409 и чужую форму", () => {
    expect(parseBatchDeleteConflict(axiosError(400, { detail: "bad" }))).toBeNull();
    expect(parseBatchDeleteConflict(axiosError(409, { detail: "строка" }))).toBeNull();
    expect(parseBatchDeleteConflict(axiosError(409, { code: "x", blockers: [{ foo: 1 }], drafts: 0 }))).toBeNull();
    expect(parseBatchDeleteConflict(new Error("сеть"))).toBeNull();
    expect(parseBatchDeleteConflict(null)).toBeNull();
  });
});

describe("blockerReasonLabel", () => {
  it("переводит причины блокеров", () => {
    expect(blockerReasonLabel("released")).toContain("released");
    expect(blockerReasonLabel("transfer №TR-1")).toContain("TR-1");
  });
});
