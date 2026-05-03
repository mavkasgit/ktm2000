import React, { useState } from "react";
import { Image, Maximize2 } from "lucide-react";
import { Button } from "@/shared/ui/Button";
import { Input } from "@/shared/ui/Input";
import { Checkbox } from "@/shared/ui/Checkbox";
import { FullscreenPhoto } from "./FullscreenPhoto";
import { getPhotoUrl } from "./getPhotoUrl";
import type { Product, ProductType, CreateProductInput, PatchProductInput } from "@/shared/api/products";

const TYPE_OPTIONS: { value: ProductType; label: string }[] = [
  { value: "finished_good", label: "Готовая продукция" },
  { value: "semi_finished", label: "Полуфабрикат" },
  { value: "component", label: "Сырье" },
  { value: "material", label: "Материал" },
];

export type DialogMode = "create" | "edit";

export function CatalogForm({
  product,
  mode,
  onSave,
  onCancel,
}: {
  product: Product | null;
  mode: DialogMode;
  onSave: (payload: CreateProductInput | PatchProductInput, mode: DialogMode) => void;
  onCancel: () => void;
}) {
  const isCreate = mode === "create";
  const [fullscreenPhoto, setFullscreenPhoto] = useState<string | null>(null);
  const [form, setForm] = useState<CreateProductInput>({
    sku: product?.sku ?? "",
    name: product?.name ?? "",
    type: product?.type ?? "finished_good",
    unit: product?.unit ?? "шт",
    is_active: product?.is_active ?? true,
    notes: product?.notes ?? null,
    profile_type: product?.profile_type ?? null,
    alloy: product?.alloy ?? null,
    color: product?.color ?? null,
    anod_type: product?.anod_type ?? null,
    length_mm: product?.length_mm ?? null,
    weight_per_meter: product?.weight_per_meter ?? null,
    quantity_per_hanger: product?.quantity_per_hanger ?? null,
    cross_section: product?.cross_section ?? null,
    is_paired_profile: product?.is_paired_profile ?? false,
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (isCreate) {
      onSave(form, mode);
    } else if (product) {
      const patch: PatchProductInput = {};
      (Object.keys(form) as Array<keyof CreateProductInput>).forEach((key) => {
        if (key === "sku") return;
        const val = form[key];
        const orig = product[key as keyof Product];
        if (val !== orig) {
          (patch as any)[key] = val;
        }
      });
      onSave(patch, mode);
    }
  };

  const update = <K extends keyof CreateProductInput>(key: K, value: CreateProductInput[K]) => {
    setForm((f) => ({ ...f, [key]: value }));
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4 mt-4">
      {fullscreenPhoto && (
        <FullscreenPhoto
          src={fullscreenPhoto}
          alt={product?.name || ""}
          onClose={() => setFullscreenPhoto(null)}
        />
      )}

      <div className="grid grid-cols-1 md:grid-cols-[320px_1fr] gap-6">
        <div className="flex flex-col gap-3">
          <div
            className="relative w-full h-96 md:h-[420px] bg-muted rounded-lg flex items-center justify-center overflow-hidden group/photo cursor-pointer hover:ring-2 ring-primary transition-all"
            onClick={() => {
              const full = product?.photo_full || product?.photo_thumb;
              if (full) setFullscreenPhoto(getPhotoUrl(full)!);
            }}
          >
            {product?.photo_full || product?.photo_thumb ? (
              <>
                <img
                  src={getPhotoUrl(product?.photo_full || product?.photo_thumb)!}
                  alt={product?.name || ""}
                  className="w-full h-full object-contain pointer-events-none"
                />
                <div className="absolute bottom-2 right-2 p-2 bg-black/50 text-white rounded-full pointer-events-none">
                  <Maximize2 className="w-5 h-5" />
                </div>
              </>
            ) : (
              <Image className="w-16 h-16 text-muted-foreground" />
            )}
          </div>
        </div>

        <div className="space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1">
              <label className="text-sm font-medium">Артикул *</label>
              <Input value={form.sku} onChange={(e) => update("sku", e.target.value)} disabled={!isCreate} placeholder="ЮП-1234" />
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium">Наименование *</label>
              <Input value={form.name} onChange={(e) => update("name", e.target.value)} placeholder="Полное название" />
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium">Тип</label>
              <select
                className="w-full h-10 rounded-md border border-input bg-background px-3 text-sm"
                value={form.type}
                onChange={(e) => update("type", e.target.value as ProductType)}
              >
                {TYPE_OPTIONS.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium">Ед. изм.</label>
              <Input value={form.unit} onChange={(e) => update("unit", e.target.value)} placeholder="шт, м, кг" />
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium">Вид профиля</label>
              <Input value={form.profile_type ?? ""} onChange={(e) => update("profile_type", e.target.value || null)} placeholder="короб, кант, рассеиватель" />
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium">Сплав</label>
              <Input value={form.alloy ?? ""} onChange={(e) => update("alloy", e.target.value || null)} placeholder="АД31, АД0" />
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium">Цвет</label>
              <Input value={form.color ?? ""} onChange={(e) => update("color", e.target.value || null)} placeholder="черный, серебро" />
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium">Тип анодирования</label>
              <Input value={form.anod_type ?? ""} onChange={(e) => update("anod_type", e.target.value || null)} placeholder="матовое, глянцевое" />
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium">Длина, мм</label>
              <Input type="number" step="0.1" value={form.length_mm ?? ""} onChange={(e) => update("length_mm", e.target.value ? parseFloat(e.target.value) : null)} />
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium">Вес погонного метра, кг/м</label>
              <Input type="number" step="0.001" value={form.weight_per_meter ?? ""} onChange={(e) => update("weight_per_meter", e.target.value ? parseFloat(e.target.value) : null)} />
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium">Кол-во на подвесе, шт</label>
              <Input type="number" value={form.quantity_per_hanger ?? ""} onChange={(e) => update("quantity_per_hanger", e.target.value ? parseInt(e.target.value) : null)} />
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium">Сечение / габариты</label>
              <Input value={form.cross_section ?? ""} onChange={(e) => update("cross_section", e.target.value || null)} placeholder="20x30, 47мм" />
            </div>
          </div>

          <div className="flex items-center gap-2 pt-1">
            <Checkbox
              id="is_paired_profile"
              checked={form.is_paired_profile ?? false}
              onCheckedChange={(checked) => update("is_paired_profile", checked === true)}
            />
            <label htmlFor="is_paired_profile" className="text-sm font-medium leading-none cursor-pointer">
              Парный профиль
            </label>
          </div>
        </div>
      </div>

      <div className="space-y-1">
        <label className="text-sm font-medium">Примечания</label>
        <textarea
          className="w-full min-h-[80px] rounded-md border border-input bg-background px-3 py-2 text-sm"
          value={form.notes ?? ""}
          onChange={(e) => update("notes", e.target.value || null)}
          placeholder="Дополнительная информация..."
        />
      </div>

      <div className="flex justify-end gap-2 pt-2">
        <Button type="button" variant="outline" onClick={onCancel}>Закрыть</Button>
        <Button type="submit">{isCreate ? "Создать" : "Сохранить"}</Button>
      </div>
    </form>
  );
}
