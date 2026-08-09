import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ruler } from "lucide-react";
import { useState, useEffect, useRef, useImperativeHandle, forwardRef } from "react";
import { Input } from "@/shared/ui/input";
import { toast } from "@/shared/ui/use-toast";
import { getErrorMessage } from "@/shared/api/client";
import { queryKeys } from "@/shared/api/queryKeys";
import {
  listProductDimensions,
  patchProductDimension,
  createProductDimension,
  type ProductDimension,
} from "../api";
import { cn } from "@/shared/utils/cn";
import { parseNumericInput } from "@/shared/lib/parseNumericInput";
import { DIMENSION_FIELDS, DIMENSION_STATE_LABELS, DIMENSION_STATES, isLengthState } from "@/shared/lib/dimensionState";
import type { DimensionState } from "@/shared/api/products";

const MODES = DIMENSION_STATES.map((value) => ({ value, label: DIMENSION_STATE_LABELS[value] }));

/**
 * Секция «Измерения» карточки продукта.
 *
 * Табы переключают dimension_state (1D / 2D / 3D).
 * 2D/3D поля — локальный state, сохраняется в product_dimensions.
 */
export type ProductDimensionsSectionHandle = {
  flushPending: () => Promise<void>;
};

export const ProductDimensionsSection = forwardRef<
  ProductDimensionsSectionHandle,
  {
    productId?: number;
    dimensionState: DimensionState;
    onDimensionStateChange: (state: DimensionState) => void;
    dimensionTypes: { id: number; code: string }[];
    readOnly?: boolean;
  }
>(function ProductDimensionsSection(
  { productId, dimensionState, onDimensionStateChange, dimensionTypes, readOnly = false },
  ref,
) {
  const queryClient = useQueryClient();

  const { data: links = [] } = useQuery({
    queryKey: queryKeys.dimensions.product(productId!),
    queryFn: () => listProductDimensions(productId!),
    enabled: !!productId,
  });

  // Локальный state для 2D/3D — code → value
  const [multiValues, setMultiValues] = useState<Record<string, string>>({});
  const dirtyRef = useRef(new Set<string>());
  // In-flight сохранения code → promise (blur-сохранения + flushPending делят их)
  const pendingRef = useRef(new Map<string, Promise<unknown>>());

  // Синхронизация из server → local state (только для чистых полей)
  useEffect(() => {
    if (isLengthState(dimensionState)) return;
    const codes = (DIMENSION_FIELDS[dimensionState as Exclude<DimensionState, "length">]).map((f) => f.code);
    setMultiValues((prev) => {
      let changed = false;
      const next = { ...prev };
      for (const code of codes) {
        if (dirtyRef.current.has(code)) continue;
        const link = links.find((l) => l.dimension_type.code === code);
        const serverValue = link?.default_value != null ? String(link.default_value) : "";
        if (next[code] !== serverValue) {
          next[code] = serverValue;
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [links, dimensionState]);

  const invalidate = () => {
    if (productId) queryClient.invalidateQueries({ queryKey: queryKeys.dimensions.product(productId) });
  };

  const onError = (error: unknown, action: string) => {
    toast({ title: `Ошибка: ${action}`, description: getErrorMessage(error), variant: "destructive" });
  };

  const patchMutation = useMutation({
    mutationFn: ({ linkId, payload }: { linkId: number; payload: { default_value: number | null } }) =>
      patchProductDimension(productId!, linkId, payload),
    onSuccess: invalidate,
    onError: (error) => onError(error, "изменение измерения"),
  });

  const createMutation = useMutation({
    mutationFn: (payload: { dimension_type_id: number; default_value: number | null }) =>
      createProductDimension(productId!, payload),
    onSuccess: invalidate,
    onError: (error) => onError(error, "создание измерения"),
  });

  const flushPending = async () => {
    if (readOnly || !productId || isLengthState(dimensionState)) return;
    const codes = (DIMENSION_FIELDS[dimensionState as Exclude<DimensionState, "length">]).map((f) => f.code);
    // Сохраняем ВСЕ поля текущей размерности (детерминированно): для кода,
    // который уже сохраняется по blur — ждём его промис, иначе сохраняем сейчас.
    const promises = codes.map((code) => pendingRef.current.get(code) ?? saveCode(code));
    await Promise.all(promises);
  };

  useImperativeHandle(ref, () => ({ flushPending }), [flushPending]);

  const handleMultiChange = (code: string, value: string) => {
    if (readOnly) return;
    setMultiValues((prev) => ({ ...prev, [code]: value }));
    dirtyRef.current.add(code);
  };

  /** Сохранить одно поле (2D/3D). Промис отслеживается в pendingRef, чтобы
   *  flushPending мог дождаться и blur-сохранений перед закрытием диалога. */
  const saveCode = (code: string): Promise<unknown> => {
    const value = multiValues[code] ?? "";
    const parsed = parseNumericInput(value);
    const link = links.find((l) => l.dimension_type.code === code);
    const dimType = dimensionTypes.find((dt) => dt.code === code);
    if (!dimType) return Promise.resolve();
    const promise = (link
      ? patchMutation.mutateAsync({ linkId: link.id, payload: { default_value: parsed } })
      : createMutation.mutateAsync({ dimension_type_id: dimType.id, default_value: parsed })
    ).catch(() => undefined);
    pendingRef.current.set(code, promise);
    void promise.finally(() => {
      if (pendingRef.current.get(code) === promise) pendingRef.current.delete(code);
    });
    return promise;
  };

  const handleMultiSave = (code: string) => {
    if (readOnly || !productId) return;
    if (!dirtyRef.current.has(code)) return;
    dirtyRef.current.delete(code);
    void saveCode(code);
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5">
        <Ruler className="w-4 h-4 text-muted-foreground" />
        <div className="flex items-center rounded-md border border-input p-0.5">
          {MODES.map((m) => (
            <button
              key={m.value}
              type="button"
              disabled={readOnly}
              onClick={() => onDimensionStateChange(m.value)}
              className={cn(
                "px-3 py-1 text-sm rounded-md transition-colors",
                m.value === dimensionState
                  ? "bg-primary text-primary-foreground cursor-default"
                  : "text-muted-foreground hover:bg-muted cursor-pointer",
              )}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>

      {!isLengthState(dimensionState) && (
        <div className="flex flex-wrap gap-3">
          {(DIMENSION_FIELDS[dimensionState as Exclude<DimensionState, "length">]).map((field) => {
            const value = multiValues[field.code] ?? "";
            const hasValue = value !== "";
            return (
              <div key={field.code} className="space-y-1 shrink-0">
                <label className="text-sm font-medium">{field.label}</label>
                <Input
                  type="number"
                  step="0.1"
                  className={cn(
                    "w-[100px]",
                    !hasValue && "bg-amber-50 border-amber-300",
                    hasValue && "bg-emerald-50 border-emerald-300",
                  )}
                  placeholder="—"
                  value={value}
                  disabled={readOnly}
                  onChange={(e) => handleMultiChange(field.code, e.target.value)}
                  onBlur={() => handleMultiSave(field.code)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      handleMultiSave(field.code);
                    }
                  }}
                />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
});
