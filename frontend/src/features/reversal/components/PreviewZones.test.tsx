import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PreviewZones } from "./PreviewZones";
import type { ActionNode, PreviewBlocker, WillReplayItem } from "@/shared/api/actions";

const emptyNode: ActionNode[] = [];
const emptyBlockers: PreviewBlocker[] = [];

describe("PreviewZones — will_replay zone (#123)", () => {
  it("показывает пустую 🟢 зону при отсутствии will_replay", () => {
    render(
      <PreviewZones
        revert={emptyNode}
        stays={emptyNode}
        blockers={emptyBlockers}
      />,
    );

    expect(screen.getByText("🟢 Воспроизведётся (0)")).toBeTruthy();
    expect(screen.getByTestId("preview-zone-replay")).toBeTruthy();
  });

  it("показывает пустую 🟢 зону при will_replay=[]", () => {
    render(
      <PreviewZones
        revert={emptyNode}
        stays={emptyNode}
        blockers={emptyBlockers}
        will_replay={[]}
      />,
    );

    expect(screen.getByText("🟢 Воспроизведётся (0)")).toBeTruthy();
  });

  it("отображает элементы will_replay с сортировкой по order", () => {
    const willReplay: WillReplayItem[] = [
      { action_id: 20, champion_id: 20, action_type: "final_release", ref_id: 5, order: 2 },
      { action_id: 15, champion_id: 15, action_type: "task_complete", ref_id: 3, order: 1 },
    ];

    render(
      <PreviewZones
        revert={emptyNode}
        stays={emptyNode}
        blockers={emptyBlockers}
        will_replay={willReplay}
      />,
    );

    expect(screen.getByText("🟢 Воспроизведётся (2)")).toBeTruthy();

    // Проверяем, что элементы отсортированы по order
    const zone = screen.getByTestId("preview-zone-replay");
    const items = zone.querySelectorAll("li");
    expect(items.length).toBe(2);

    // Первый элемент — order=1 (task_complete)
    expect(items[0].textContent).toContain("#15");
    expect(items[0].textContent).toContain("task_complete");
    expect(items[0].textContent).toContain("порядок 1");

    // Второй элемент — order=2 (final_release)
    expect(items[1].textContent).toContain("#20");
    expect(items[1].textContent).toContain("final_release");
    expect(items[1].textContent).toContain("порядок 2");
  });

  it("показывает ref_id когда он не null", () => {
    const willReplay: WillReplayItem[] = [
      { action_id: 10, champion_id: 10, action_type: "return_to_stock", ref_id: 42, order: 1 },
    ];

    render(
      <PreviewZones
        revert={emptyNode}
        stays={emptyNode}
        blockers={emptyBlockers}
        will_replay={willReplay}
      />,
    );

    expect(screen.getByText(/объект #42/)).toBeTruthy();
  });

  it("не показывает ref_id когда он null", () => {
    const willReplay: WillReplayItem[] = [
      { action_id: 10, champion_id: 10, action_type: "manual_adjustment", ref_id: null, order: 1 },
    ];

    render(
      <PreviewZones
        revert={emptyNode}
        stays={emptyNode}
        blockers={emptyBlockers}
        will_replay={willReplay}
      />,
    );

    expect(screen.queryByText(/объект/)).toBeNull();
  });
});
