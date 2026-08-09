import React, { useEffect, useRef, useState } from "react";
import { Input } from "@/shared/ui/input";
import { cn } from "@/shared/utils/cn";
import { parseNumericInput } from "@/shared/lib/parseNumericInput";

function parseFieldValue(text: string): { ok: true; value: number | null } | { ok: false } {
  if (text.trim() === "") return { ok: true, value: null };
  const num = parseNumericInput(text, { allowComma: true });
  if (num == null || num <= 0) return { ok: false };
  return { ok: true, value: num };
}

/** Inline-инпут периметра/габарита: autosave c дебаунсом, валидация >0 (#64, п. 16). */
export function HangerFieldCell({
  value,
  disabled,
  rowInvalid,
  invalidReason,
  onCommit,
  ariaLabel,
}: {
  value: number | null;
  disabled: boolean;
  rowInvalid: boolean;
  invalidReason: string | null;
  onCommit: (next: number | null) => Promise<void>;
  ariaLabel: string;
}) {
  const savedText = value == null ? "" : String(value);
  const [draft, setDraft] = useState(savedText);
  const [invalid, setInvalid] = useState(false);
  const committing = useRef(false);

  useEffect(() => {
    setDraft(savedText);
    setInvalid(false);
  }, [savedText]);

  const parsed = parseFieldValue(draft);
  const dirty = draft !== savedText;

  useEffect(() => {
    if (!dirty) return;
    if (!parsed.ok) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    if ((parsed.value ?? null) === (value ?? null)) return;
    const timer = window.setTimeout(() => {
      if (committing.current) return;
      committing.current = true;
      void onCommit(parsed.value).finally(() => {
        committing.current = false;
      });
    }, 700);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft, dirty, parsed.ok]);

  const handleBlur = () => {
    if (committing.current) return;
    if (!dirty) return;
    if (!parsed.ok) {
      // Инвалидный draft (≤0) откатывается к сохранённому значению (#64).
      setDraft(savedText);
      setInvalid(false);
      return;
    }
    committing.current = true;
    void onCommit(parsed.value).finally(() => {
      committing.current = false;
    });
  };

  const highlighted = invalid || rowInvalid;
  return (
    <Input
      type="number"
      step="0.1"
      inputMode="decimal"
      aria-label={ariaLabel}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={handleBlur}
      onClick={(e) => e.stopPropagation()}
      disabled={disabled}
      className={cn(
        "h-8 w-24 min-w-24 text-sm bg-background",
        highlighted && "border-destructive focus-visible:ring-destructive",
      )}
      title={
        invalid
          ? "Значение должно быть больше 0 — сохранение заблокировано"
          : rowInvalid
            ? invalidReason ?? undefined
            : undefined
      }
    />
  );
}
