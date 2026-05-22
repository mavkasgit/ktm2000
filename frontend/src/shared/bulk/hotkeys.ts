import { useEffect } from "react";
import type React from "react";
import type { BulkId } from "./selection";

export interface BulkHotkeyConfig<TId extends BulkId> {
  scopeRef: React.RefObject<HTMLElement>;
  filteredIds: TId[];
  hasSelection: boolean;
  disabled?: boolean;
  isRunning?: boolean;
  selectAllFiltered: (ids: TId[]) => void;
  clear: () => void;
  runPrimary: () => void;
}

export function isEditableTarget(target: EventTarget | null): boolean {
  if (!target || typeof target !== "object") return false;
  const element = target as { tagName?: string; isContentEditable?: boolean };
  const tag = element.tagName?.toLowerCase();
  return Boolean(element.isContentEditable || tag === "input" || tag === "textarea" || tag === "select");
}

export function isHotkeyInScope(scope: HTMLElement | null, target: EventTarget | null): boolean {
  if (!scope) return false;
  if (!target) return false;
  return scope.contains(target as Node);
}

export function useBulkHotkeys<TId extends BulkId>({
  scopeRef,
  filteredIds,
  hasSelection,
  disabled,
  isRunning,
  selectAllFiltered,
  clear,
  runPrimary,
}: BulkHotkeyConfig<TId>) {
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (disabled || isEditableTarget(event.target)) return;
      if (!isHotkeyInScope(scopeRef.current, event.target)) return;

      const mod = event.ctrlKey || event.metaKey;
      if (mod && event.key.toLowerCase() === "a") {
        event.preventDefault();
        selectAllFiltered(filteredIds);
        return;
      }
      if (event.key === "Escape" && hasSelection) {
        event.preventDefault();
        clear();
        return;
      }
      if (mod && event.key === "Enter" && hasSelection && !isRunning) {
        event.preventDefault();
        runPrimary();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [clear, disabled, filteredIds, hasSelection, isRunning, runPrimary, scopeRef, selectAllFiltered]);
}
