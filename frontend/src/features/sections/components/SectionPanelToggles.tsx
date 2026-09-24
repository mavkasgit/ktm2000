import { Button } from "@/shared/ui";

export type SectionContentMode = "tasks" | "plan" | "balances";

const MODES: { id: SectionContentMode; label: string }[] = [
  { id: "tasks", label: "Задания" },
  { id: "plan", label: "План" },
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
          className={`h-10 px-4 text-xl font-bold leading-tight whitespace-nowrap ${
            mode === id ? "" : "text-slate-700 hover:bg-white/80 hover:text-slate-900"
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
  return mode === "tasks";
}

export function isPlanPanelVisible(mode: SectionContentMode): boolean {
  return mode === "plan";
}

export function isBalancesPanelVisible(mode: SectionContentMode): boolean {
  return mode === "balances";
}