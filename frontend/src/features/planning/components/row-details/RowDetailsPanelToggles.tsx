import { Button } from "@/shared/ui";
import { type RowDetailsContentMode } from "./types";

const MODES: { id: RowDetailsContentMode; label: string }[] = [
  { id: "stages", label: "Этапы" },
  { id: "events", label: "События" },
];

type RowDetailsPanelTogglesProps = {
  mode: RowDetailsContentMode;
  onChange: (mode: RowDetailsContentMode) => void;
};

export function RowDetailsPanelToggles({ mode, onChange }: RowDetailsPanelTogglesProps) {
  return (
    <div className="inline-flex items-center rounded-md border bg-muted/40 p-0.5">
      {MODES.map(({ id, label }) => (
        <Button
          key={id}
          variant={mode === id ? "default" : "ghost"}
          size="sm"
          className={`h-7 px-2.5 text-xs whitespace-nowrap ${
            mode === id ? "" : "text-muted-foreground hover:text-foreground"
          }`}
          onClick={() => onChange(id)}
        >
          {label}
        </Button>
      ))}
    </div>
  );
}