import React, { useCallback, useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { searchProductsForAlias } from "@/shared/api/products";
import type { AliasSuggestion } from "@/shared/api/products";

export function ProductSearchMulti({
  values,
  onChange,
  onAliasClick,
  excludeSku,
  excludeValues,
  pairedOnly,
  placeholder = "Поиск по артикулу",
  disabled = false,
}: {
  values: string[];
  onChange: (values: string[]) => void;
  onAliasClick?: (sku: string) => void;
  excludeSku?: string;
  excludeValues?: string[];
  pairedOnly?: boolean;
  placeholder?: string;
  disabled?: boolean;
}) {
  const [search, setSearch] = useState("");
  const [suggestions, setSuggestions] = useState<AliasSuggestion[]>([]);
  const [loading, setLoading] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>();

  const doSearch = useCallback(
    async (q: string) => {
      setLoading(true);
      try {
        const results = await searchProductsForAlias(q, {
          excludeSku,
          excludeAliases: [...values, ...(excludeValues || [])],
          pairedOnly,
          limit: 20,
        });
        setSuggestions(results);
      } catch {
        setSuggestions([]);
      } finally {
        setLoading(false);
      }
    },
    [excludeSku, excludeValues, values, pairedOnly]
  );

  const handleSearchChange = (value: string) => {
    setSearch(value);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      doSearch(value.trim());
      setDropdownOpen(true);
    }, 200);
  };

  const addFromSuggestion = (suggestion: AliasSuggestion) => {
    if (!values.includes(suggestion.sku)) {
      onChange([...values, suggestion.sku]);
    }
    setSearch("");
    setSuggestions([]);
    setDropdownOpen(false);
  };

  const remove = (index: number) => {
    const next = [...values];
    next.splice(index, 1);
    onChange(next);
  };

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  return (
    <div className="space-y-2" ref={ref}>
      {values.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {values.map((val, i) => (
            <span
              key={i}
              className={`inline-flex items-center gap-1 px-2 py-0.5 rounded border border-transparent text-xs transition-colors ${onAliasClick ? "cursor-pointer hover:border-primary hover:bg-secondary" : "bg-secondary text-secondary-foreground"}`}
              onClick={() => onAliasClick?.(val)}
              title={onAliasClick ? "Перейти к профилю" : undefined}
            >
              {val}
              {!disabled && (
                <button
                  type="button"
                  className="ml-0.5 hover:text-destructive cursor-pointer opacity-60 hover:opacity-100 transition-opacity"
                  onClick={(e) => { e.stopPropagation(); remove(i); }}
                >
                  <X className="w-3 h-3" />
                </button>
              )}
            </span>
          ))}
        </div>
      )}
      {!disabled && (
        <div className="relative">
          <input
            className="w-48 h-10 rounded-md border border-input bg-background px-3 text-sm outline-none placeholder:text-muted-foreground"
            placeholder={placeholder}
            value={search}
            onChange={(e) => handleSearchChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                setDropdownOpen(false);
                setSearch("");
              }
            }}
            onFocus={() => {
              doSearch(search.trim());
              setDropdownOpen(true);
            }}
          />

          {dropdownOpen && (
            <div className="absolute z-50 w-48 left-0 mt-1 bg-popover border rounded-md shadow-lg max-h-48 overflow-y-auto">
              {loading && (
                <div className="px-3 py-1 text-sm text-muted-foreground">Поиск...</div>
              )}
              {!loading && suggestions.length === 0 && search.trim() && (
                <div className="px-3 py-1 text-sm text-muted-foreground">Ничего не найдено</div>
              )}
              {!loading && suggestions.length === 0 && !search.trim() && (
                <div className="px-3 py-1 text-sm text-muted-foreground">Нет доступных артикулов</div>
              )}
              {!loading && suggestions.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  className="w-full text-left px-3 py-1 text-sm hover:bg-muted cursor-pointer"
                  onClick={() => addFromSuggestion(s)}
                >
                  <span className="font-medium">{s.sku}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
