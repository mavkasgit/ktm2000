import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Ruler, Trash2 } from "lucide-react";
import { Button } from "@/shared/ui/Button";
import { Input } from "@/shared/ui/Input";
import { Checkbox } from "@/shared/ui/Checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/shared/ui/Select";
import { toast } from "@/shared/ui/use-toast";
import { getErrorMessage } from "@/shared/api/client";
import { queryKeys } from "@/shared/api/queryKeys";
import {
  createProductDimension,
  deleteProductDimension,
  listDimensionTypes,
  listProductDimensions,
  patchProductDimension,
  type ProductDimension,
} from "../api";

/**
 * Секция «Измерения» карточки продукта: привязанные измерения с типовым
 * размером (default_value), добавление/изменение/удаление (ADR-0001, п. 3).
 */
export function ProductDimensionsSection({
  productId,
  readOnly = false,
}: {
  productId: number;
  readOnly?: boolean;
}) {
  const queryClient = useQueryClient();
  const [addTypeId, setAddTypeId] = useState<string>("");
  const [addDefaultValue, setAddDefaultValue] = useState("");
  const [addIsRequired, setAddIsRequired] = useState(true);

  const { data: types = [] } = useQuery({
    queryKey: queryKeys.dimensions.types(),
    queryFn: listDimensionTypes,
  });

  const { data: links = [], isLoading } = useQuery({
    queryKey: queryKeys.dimensions.product(productId),
    queryFn: () => listProductDimensions(productId),
  });

  const availableTypes = useMemo(
    () => types.filter((t) => !links.some((l) => l.dimension_type_id === t.id)),
    [types, links],
  );

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.dimensions.product(productId) });
  };

  const onError = (error: unknown, action: string) => {
    toast({ title: `Ошибка: ${action}`, description: getErrorMessage(error), variant: "destructive" });
  };

  const createMutation = useMutation({
    mutationFn: () =>
      createProductDimension(productId, {
        dimension_type_id: Number(addTypeId),
        is_required: addIsRequired,
        default_value: addDefaultValue.trim() ? parseFloat(addDefaultValue) : null,
      }),
    onSuccess: () => {
      setAddTypeId("");
      setAddDefaultValue("");
      setAddIsRequired(true);
      invalidate();
    },
    onError: (error) => onError(error, "добавление измерения"),
  });

  const patchMutation = useMutation({
    mutationFn: ({ linkId, payload }: { linkId: number; payload: { is_required?: boolean; default_value?: number | null } }) =>
      patchProductDimension(productId, linkId, payload),
    onSuccess: invalidate,
    onError: (error) => onError(error, "изменение измерения"),
  });

  const deleteMutation = useMutation({
    mutationFn: (linkId: number) => deleteProductDimension(productId, linkId),
    onSuccess: invalidate,
    onError: (error) => onError(error, "удаление измерения"),
  });

  const commitDefaultValue = (link: ProductDimension, raw: string) => {
    const trimmed = raw.trim();
    const parsed = trimmed ? parseFloat(trimmed) : null;
    if (parsed !== null && !Number.isFinite(parsed)) return;
    if (parsed === (link.default_value ?? null)) return;
    patchMutation.mutate({ linkId: link.id, payload: { default_value: parsed } });
  };

  return (
    <div className="space-y-2">
      <label className="text-sm font-medium flex items-center gap-1.5">
        <Ruler className="w-4 h-4" />
        Измерения
      </label>

      {isLoading ? (
        <p className="text-xs text-muted-foreground">Загрузка измерений…</p>
      ) : links.length === 0 ? (
        <p className="text-xs text-muted-foreground">Измерения не привязаны — безразмерные штуки.</p>
      ) : (
        <div className="space-y-1.5">
          {links.map((link) => (
            <div key={link.id} className="flex items-center gap-3 rounded-md border border-input px-3 py-2 text-sm">
              <span className="min-w-32 font-medium">
                {link.dimension_type.name}
                <span className="text-muted-foreground font-normal"> ({link.dimension_type.code})</span>
              </span>
              <div className="flex items-center gap-1.5">
                <Input
                  type="number"
                  className="w-28 h-8"
                  placeholder="Типовой размер"
                  defaultValue={link.default_value ?? ""}
                  disabled={readOnly || patchMutation.isPending}
                  onBlur={(e) => commitDefaultValue(link, e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      commitDefaultValue(link, (e.target as HTMLInputElement).value);
                    }
                  }}
                />
                <span className="text-muted-foreground">{link.dimension_type.unit}</span>
              </div>
              <div className="flex items-center gap-1.5">
                <Checkbox
                  id={`dim-required-${link.id}`}
                  checked={link.is_required}
                  disabled={readOnly || patchMutation.isPending}
                  onCheckedChange={(checked) =>
                    patchMutation.mutate({ linkId: link.id, payload: { is_required: checked === true } })
                  }
                />
                <label htmlFor={`dim-required-${link.id}`} className="text-xs cursor-pointer">
                  Обязательное
                </label>
              </div>
              {!readOnly && (
                <button
                  type="button"
                  className="ml-auto text-muted-foreground hover:text-destructive"
                  disabled={deleteMutation.isPending}
                  onClick={() => deleteMutation.mutate(link.id)}
                  title="Удалить привязку"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {!readOnly && (
        <div className="flex items-center gap-2">
          <Select value={addTypeId} onValueChange={setAddTypeId}>
            <SelectTrigger className="w-48 h-9">
              <SelectValue placeholder="Тип измерения" />
            </SelectTrigger>
            <SelectContent>
              {availableTypes.length === 0 ? (
                <div className="px-3 py-2 text-xs text-muted-foreground">Нет доступных типов</div>
              ) : (
                availableTypes.map((t) => (
                  <SelectItem key={t.id} value={String(t.id)}>
                    {t.name} ({t.code}, {t.unit})
                  </SelectItem>
                ))
              )}
            </SelectContent>
          </Select>
          <Input
            type="number"
            className="w-32 h-9"
            placeholder="Типовой размер"
            value={addDefaultValue}
            onChange={(e) => setAddDefaultValue(e.target.value)}
          />
          <div className="flex items-center gap-1.5">
            <Checkbox
              id="dim-add-required"
              checked={addIsRequired}
              onCheckedChange={(checked) => setAddIsRequired(checked === true)}
            />
            <label htmlFor="dim-add-required" className="text-xs cursor-pointer">
              Обязательное
            </label>
          </div>
          <Button
            type="button"
            size="sm"
            className="h-9"
            disabled={!addTypeId || createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            <Plus className="w-3 h-3 mr-1" />
            Добавить
          </Button>
        </div>
      )}
    </div>
  );
}
