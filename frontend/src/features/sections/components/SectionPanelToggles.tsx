import { Button } from "@/shared/ui";

export type SectionContentMode = "both" | "tasks" | "balances";

const MODES: { id: SectionContentMode; label: string }[] = [
  { id: "both", label: "Всё" },
  { id: "tasks", label: "Задания" },
  { id: "balances", label: "Остатки" },
];

type SectionPanelTogglesProps = {
  mode: SectionContentMode;
  onChange: (mode: SectionContentMode) => void;
};

export function SectionPanelToggles({ mode, onChange }: SectionPanelTogglesProps) {
  return (
    <div className="inline-flex items-center rounded-md border border-white/80 bg-white/70 p-0.5">
      {MODES.map(({ id, label }) => (
        <Button
          key={id}
          variant={mode === id ? "default" : "ghost"}
          size="sm"
          className={`h-7 px-2.5 text-xs whitespace-nowrap ${
            mode === id ? "" : "text-slate-600 hover:bg-white/80 hover:text-slate-900"
          }`}
          onClick={() => onChange(id)}
        >
          {label}
        </Button>
      ))}
    </div>
  );
}

export function isTasksPanelVisible(mode: SectionContentMode): boolean {
  return mode === "both" || mode === "tasks";
}

export function isBalancesPanelVisible(mode: SectionContentMode): boolean {
  return mode === "both" || mode === "balances";
}