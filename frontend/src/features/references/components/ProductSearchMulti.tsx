import { useCallback } from "react";
import { X } from "lucide-react";
import { searchProductsForAlias } from "@/shared/api/products";
import type { AliasSuggestion } from "@/shared/api/products";
import { ProductSkuSearchInput } from "./ProductSkuSearchInput";

export function ProductSearchMulti({
  values,
  onChange,
  onAliasClick,
  excludeSku,
  excludeValues,
  pairedOnly,
  showPairedStatus = true,
  placeholder = "Поиск по артикулу",
  disabled = false,
}: {
  values: string[];
  onChange: (values: string[]) => void;
  onAliasClick?: (sku: string) => void;
  excludeSku?: string;
  excludeValues?: string[];
  pairedOnly?: boolean;
  showPairedStatus?: boolean;
  placeholder?: string;
  disabled?: boolean;
}) {
  const fetchSuggestions = useCallback(
    (q: string) =>
      searchProductsForAlias(q, {
        excludeSku,
        excludeAliases: [...values, ...(excludeValues || [])],
        pairedOnly,
        limit: 20,
      }),
    [excludeSku, excludeValues, values, pairedOnly],
  );

  const addFromSuggestion = (suggestion: AliasSuggestion) => {
    if (!values.includes(suggestion.sku)) {
      onChange([...values, suggestion.sku]);
    }
  };

  const remove = (index: number) => {
    const next = [...values];
    next.splice(index, 1);
    onChange(next);
  };

  return (
    <div className="space-y-1.5">
      {!disabled && (
        <ProductSkuSearchInput
          fetchSuggestions={fetchSuggestions}
          onSelect={addFromSuggestion}
          placeholder={placeholder}
          showPairedStatus={showPairedStatus}
        />
      )}
      {values.length > 0 && (
        <div className="grid grid-cols-2 gap-1.5">
          {values.map((val, i) => (
            <div
              key={i}
              className="h-8 inline-flex items-center gap-1 px-2 rounded-md border border-transparent bg-secondary text-secondary-foreground text-xs transition-colors"
            >
              <span
                className={`flex-1 min-w-0 truncate ${onAliasClick ? "cursor-pointer hover:text-primary" : ""}`}
                onClick={() => onAliasClick?.(val)}
                title={onAliasClick ? "Перейти к профилю" : undefined}
              >
                {val}
              </span>
              {!disabled && (
                <button
                  type="button"
                  className="ml-0.5 hover:text-destructive cursor-pointer opacity-60 hover:opacity-100 transition-opacity shrink-0"
                  onClick={(e) => { e.stopPropagation(); remove(i); }}
                >
                  <X className="w-3 h-3" />
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
