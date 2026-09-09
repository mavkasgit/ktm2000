import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import type { AliasSuggestion } from "@/shared/api/products";

/**
 * Общий серч-бар выбора артикула (эквиваленты + пары): input + выпадающий
 * список саджестов в едином стиле. Данные поставляет вызывающий через
 * fetchSuggestions — компонент владеет только UI-состоянием (поиск,
 * дропдаун, empty-состояния). Выбор — клик по строке → onSelect.
 */
export function ProductSkuSearchInput({
  fetchSuggestions,
  onSelect,
  placeholder = "Поиск по артикулу",
  disabled = false,
  showPairedStatus = true,
  busy = false,
}: {
  fetchSuggestions: (q: string) => Promise<AliasSuggestion[]>;
  onSelect: (suggestion: AliasSuggestion) => void;
  placeholder?: string;
  disabled?: boolean;
  showPairedStatus?: boolean;
  /** Внешняя занятость (например, POST пары): спиннер поверх input. */
  busy?: boolean;
}) {
  const [search, setSearch] = useState("");
  const [suggestions, setSuggestions] = useState<AliasSuggestion[]>([]);
  const [loading, setLoading] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const timer = useRef<number | undefined>(undefined);

  const doSearch = useCallback(
    async (q: string) => {
      setLoading(true);
      try {
        setSuggestions(await fetchSuggestions(q));
      } catch {
        setSuggestions([]);
      } finally {
        setLoading(false);
      }
    },
    [fetchSuggestions],
  );

  const handleSearchChange = (value: string) => {
    setSearch(value);
    clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      doSearch(value.trim());
      setDropdownOpen(true);
    }, 200);
  };

  const select = (suggestion: AliasSuggestion) => {
    onSelect(suggestion);
    setSearch("");
    setSuggestions([]);
    setDropdownOpen(false);
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

  useEffect(
    () => () => {
      clearTimeout(timer.current);
    },
    [],
  );

  return (
    <div ref={ref} className="relative">
      <input
        className="w-full h-9 rounded-md border border-input bg-background px-3 text-sm outline-none placeholder:text-muted-foreground"
        placeholder={placeholder}
        value={search}
        disabled={disabled}
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
      {(loading || busy) && (
        <Loader2 className="h-4 w-4 animate-spin absolute right-2 top-2.5 text-muted-foreground" />
      )}
      {dropdownOpen && !disabled && (
        <div className="absolute z-50 w-full left-0 mt-1 bg-popover border rounded-md shadow-lg max-h-48 overflow-y-auto">
          {loading && (
            <div className="px-3 py-1 text-sm text-muted-foreground">Поиск...</div>
          )}
          {!loading && suggestions.length === 0 && search.trim() && (
            <div className="px-3 py-1 text-sm text-muted-foreground">Ничего не найдено</div>
          )}
          {!loading && suggestions.length === 0 && !search.trim() && (
            <div className="px-3 py-1 text-sm text-muted-foreground">Нет доступных артикулов</div>
          )}
          {!loading &&
            suggestions.map((s) => (
              <button
                key={s.id}
                type="button"
                className="w-full text-left px-3 py-1.5 text-sm hover:bg-muted cursor-pointer flex justify-between items-center gap-2"
                onClick={() => select(s)}
              >
                <span className="font-medium shrink-0">{s.sku}</span>
                <span className="text-xs text-muted-foreground truncate flex-1 text-right">
                  {s.name}
                </span>
                {showPairedStatus && !s.is_paired_profile && (
                  <span className="text-[10px] bg-amber-100 text-amber-800 px-1.5 py-0.5 rounded font-normal shrink-0">
                    непарный
                  </span>
                )}
              </button>
            ))}
        </div>
      )}
    </div>
  );
}
