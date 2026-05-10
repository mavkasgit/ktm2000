import React, { useEffect, useImperativeHandle, useState, forwardRef, useCallback } from "react";
import { Image, Maximize2, Camera, Trash2, Plus, Minus } from "lucide-react";
import { Button } from "@/shared/ui/Button";
import { Input } from "@/shared/ui/Input";
import { Checkbox } from "@/shared/ui/Checkbox";
import { FullscreenPhoto } from "./FullscreenPhoto";
import { ImageUploadModal } from "./ImageUploadModal";
import { ProductSearchMulti } from "./ProductSearchMulti";
import { getPhotoUrl } from "./getPhotoUrl";
import { uploadProductPhoto } from "@/shared/api/products";
import type { Product, CreateProductInput, PatchProductInput } from "@/shared/api/products";

export type DialogMode = "create" | "edit";

export type FieldChange = { field: string; label: string; from: string | number | boolean | null; to: string | number | boolean | null };

function normalizeLengths(lengths: Array<number | null | undefined>): number[] {
  return [...new Set(lengths.filter((v): v is number => typeof v === "number" && Number.isFinite(v) && v > 0))]
    .sort((a, b) => a - b);
}

function getProductLengths(product: Product | null): number[] {
  if (!product) return [];
  return normalizeLengths([...(product.lengths_mm ?? []), product.length_mm ?? undefined]);
}

function getChanges(form: CreateProductInput, product: Product | null, isCreate: boolean): FieldChange[] {
  if (isCreate || !product) return [];
  const changes: FieldChange[] = [];
  const eq = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
  const formLengths = normalizeLengths(form.lengths_mm ?? []);
  const productLengths = getProductLengths(product);

  if (!eq(form.name, product.name)) changes.push({ field: "name", label: "Наименование", from: product.name, to: form.name ?? "" });
  if (!eq(form.type, product.type)) changes.push({ field: "type", label: "Тип", from: product.type, to: form.type ?? "" });
  if (!eq(form.unit, product.unit)) changes.push({ field: "unit", label: "Ед. изм.", from: product.unit, to: form.unit ?? "" });
  if (!eq(form.is_active, product.is_active)) changes.push({ field: "is_active", label: "Активен", from: product.is_active ? "Да" : "Нет", to: form.is_active ? "Да" : "Нет" });
  if (!eq(form.notes, product.notes)) changes.push({ field: "notes", label: "Примечания", from: product.notes ?? "—", to: form.notes ?? "—" });
  if (!eq(form.profile_type, product.profile_type)) changes.push({ field: "profile_type", label: "Тип профиля", from: product.profile_type ?? "—", to: form.profile_type ?? "—" });
  if (!eq(form.alloy, product.alloy)) changes.push({ field: "alloy", label: "Сплав", from: product.alloy ?? "—", to: form.alloy ?? "—" });
  if (!eq(form.color, product.color)) changes.push({ field: "color", label: "Цвет", from: product.color ?? "—", to: form.color ?? "—" });
  if (!eq(form.anod_type, product.anod_type)) changes.push({ field: "anod_type", label: "Тип анод.", from: product.anod_type ?? "—", to: form.anod_type ?? "—" });
  if (!eq(form.weight_per_meter, product.weight_per_meter)) changes.push({ field: "weight_per_meter", label: "Вес/м", from: product.weight_per_meter ?? "—", to: form.weight_per_meter ?? "—" });
  if (!eq(form.quantity_per_hanger, product.quantity_per_hanger)) changes.push({ field: "quantity_per_hanger", label: "Кол-во на подвесе", from: product.quantity_per_hanger ?? "—", to: form.quantity_per_hanger ?? "—" });
  if (!eq(form.cross_section, product.cross_section)) changes.push({ field: "cross_section", label: "Сечение", from: product.cross_section ?? "—", to: form.cross_section ?? "—" });
  if (!eq(form.is_paired_profile, product.is_paired_profile)) changes.push({ field: "is_paired_profile", label: "Парный профиль", from: product.is_paired_profile ? "Да" : "Нет", to: form.is_paired_profile ? "Да" : "Нет" });
  if (!eq(form.skip_shot_blast, product.skip_shot_blast)) changes.push({ field: "skip_shot_blast", label: "Не дробеструится", from: product.skip_shot_blast ? "Да" : "Нет", to: form.skip_shot_blast ? "Да" : "Нет" });
  if (!eq(form.aliases ?? [], product.aliases ?? [])) changes.push({ field: "aliases", label: "Эквиваленты", from: (product.aliases ?? []).join(", ") || "—", to: (form.aliases ?? []).join(", ") || "—" });
  if (!eq(formLengths, productLengths)) changes.push({ field: "lengths_mm", label: "Длины", from: productLengths.join(", ") || "—", to: formLengths.join(", ") || "—" });
  if (!eq(form.is_laminated ?? false, product.is_laminated)) changes.push({ field: "is_laminated", label: "Ламинируется", from: product.is_laminated ? "Да" : "Нет", to: form.is_laminated ? "Да" : "Нет" });
  return changes;
}

export interface CatalogFormRef {
  save: () => void;
}

export const CatalogForm = forwardRef<CatalogFormRef, {
  product: Product | null;
  mode: DialogMode;
  onSave: (payload: CreateProductInput | PatchProductInput, mode: DialogMode) => void;
  onCancel: () => void;
  onDelete?: () => void;
  onAliasClick?: (sku: string) => void;
  onDirtyChange?: (dirty: boolean) => void;
  onChangesChange?: (changes: FieldChange[]) => void;
}>(function CatalogForm({
  product,
  mode,
  onSave,
  onCancel,
  onDelete,
  onAliasClick,
  onDirtyChange,
  onChangesChange,
}, ref) {
  const isCreate = mode === "create";
  const initialLengths = getProductLengths(product);
  const [fullscreenPhoto, setFullscreenPhoto] = useState<string | null>(null);
  const [localPhotoFull, setLocalPhotoFull] = useState<string | null>(null);
  const [localPhotoThumb, setLocalPhotoThumb] = useState<string | null>(null);
  const [uploadFullModal, setUploadFullModal] = useState(false);
  const [uploadThumbModal, setUploadThumbModal] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [photoVersion, setPhotoVersion] = useState(0);
  const [newLength, setNewLength] = useState("");
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
    length_mm: initialLengths[0] ?? product?.length_mm ?? null,
    weight_per_meter: product?.weight_per_meter ?? null,
    quantity_per_hanger: product?.quantity_per_hanger ?? null,
    cross_section: product?.cross_section ?? null,
    is_paired_profile: product?.is_paired_profile ?? false,
    skip_shot_blast: product?.skip_shot_blast ?? false,
    aliases: product?.aliases ?? [],
    lengths_mm: initialLengths,
    is_laminated: product?.is_laminated ?? false,
  });

  const setLengths = useCallback((values: number[]) => {
    const normalized = normalizeLengths(values);
    setForm((f) => ({
      ...f,
      lengths_mm: normalized,
      // Keep legacy scalar field in sync with the first length.
      length_mm: normalized[0] ?? null,
    }));
  }, []);

  const commitLength = () => {
    const val = parseFloat(newLength);
    if (isNaN(val) || val <= 0) return;
    setLengths([...(form.lengths_mm ?? []), val]);
    setNewLength("");
  };

  const buildPatch = useCallback((): PatchProductInput => {
    if (!product) return {};
    const patch: PatchProductInput = {};
    const eq = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
    const formLengths = normalizeLengths(form.lengths_mm ?? []);
    const productLengths = getProductLengths(product);
    const formPrimaryLength = formLengths[0] ?? null;
    const productPrimaryLength = productLengths[0] ?? (product.length_mm ?? null);

    if (!eq(form.name, product.name)) patch.name = form.name;
    if (!eq(form.type, product.type)) patch.type = form.type;
    if (!eq(form.unit, product.unit)) patch.unit = form.unit;
    if (!eq(form.is_active, product.is_active)) patch.is_active = form.is_active;
    if (!eq(form.notes, product.notes)) patch.notes = form.notes;
    if (!eq(form.profile_type, product.profile_type)) patch.profile_type = form.profile_type;
    if (!eq(form.alloy, product.alloy)) patch.alloy = form.alloy;
    if (!eq(form.color, product.color)) patch.color = form.color;
    if (!eq(form.anod_type, product.anod_type)) patch.anod_type = form.anod_type;
    if (!eq(formPrimaryLength, productPrimaryLength)) patch.length_mm = formPrimaryLength;
    if (!eq(form.weight_per_meter, product.weight_per_meter)) patch.weight_per_meter = form.weight_per_meter;
    if (!eq(form.quantity_per_hanger, product.quantity_per_hanger)) patch.quantity_per_hanger = form.quantity_per_hanger;
    if (!eq(form.cross_section, product.cross_section)) patch.cross_section = form.cross_section;
    if (!eq(form.is_paired_profile, product.is_paired_profile)) patch.is_paired_profile = form.is_paired_profile;
    if (!eq(form.skip_shot_blast, product.skip_shot_blast)) patch.skip_shot_blast = form.skip_shot_blast;
    if (!eq(form.aliases ?? [], product.aliases ?? [])) patch.aliases = form.aliases;
    if (!eq(formLengths, productLengths)) patch.lengths_mm = formLengths;
    if (!eq(form.is_laminated ?? false, product.is_laminated)) patch.is_laminated = form.is_laminated;
    return patch;
  }, [form, product]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (isCreate) {
      onSave(form, mode);
    } else if (product) {
      onSave(buildPatch(), mode);
    }
  };

  useImperativeHandle(ref, () => ({
    save: () => {
      if (isCreate) {
        onSave(form, mode);
      } else if (product) {
        onSave(buildPatch(), mode);
      }
    },
  }), [form, product, isCreate, mode, onSave, buildPatch]);

  const update = <K extends keyof CreateProductInput>(key: K, value: CreateProductInput[K]) => {
    setForm((f) => ({ ...f, [key]: value }));
  };

  const changes = getChanges(form, product, isCreate);
  const isDirty = changes.length > 0;
  useEffect(() => {
    onDirtyChange?.(isDirty);
    onChangesChange?.(changes);
  }, [isDirty, onDirtyChange, onChangesChange, changes]);

  // Cleanup blob URLs on unmount
  useEffect(() => {
    return () => {
      if (localPhotoFull?.startsWith("blob:")) URL.revokeObjectURL(localPhotoFull);
      if (localPhotoThumb?.startsWith("blob:")) URL.revokeObjectURL(localPhotoThumb);
    };
  }, [localPhotoFull, localPhotoThumb]);

  const handlePhotoUpload = async (file: File, target: "full" | "thumb") => {
    if (!product?.id) return;
    setUploading(true);
    try {
      const updated = await uploadProductPhoto(product.id, file, target);
      if (target === "full") {
        if (localPhotoFull?.startsWith("blob:")) URL.revokeObjectURL(localPhotoFull);
        setLocalPhotoFull(getPhotoUrl(updated.photo_full));
      } else {
        if (localPhotoThumb?.startsWith("blob:")) URL.revokeObjectURL(localPhotoThumb);
        setLocalPhotoThumb(getPhotoUrl(updated.photo_thumb));
      }
      setPhotoVersion((v) => v + 1);
    } catch {
    } finally {
      setUploading(false);
    }
  };

  const handlePhotoSelect = (file: File, target: "full" | "thumb") => {
    if (isCreate) return;
    handlePhotoUpload(file, target);
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

      {isDirty && !isCreate && changes.length > 0 && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-3">
          <p className="text-sm font-medium text-blue-900 mb-1">Изменения:</p>
          <ul className="text-xs text-blue-800 space-y-0.5 max-h-24 overflow-auto">
            {changes.map((c) => (
              <li key={c.field} className="flex gap-1">
                <span className="font-medium">{c.label}:</span>
                <span className="text-red-600 line-through">{String(c.from)}</span>
                <span>→</span>
                <span className="text-green-700">{String(c.to)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-[320px_1fr] gap-6">
        <div className="flex flex-col gap-3">
          {/* Main photo */}
          <div
            className="relative w-full h-96 md:h-[420px] bg-muted rounded-lg flex items-center justify-center overflow-hidden group/photo cursor-pointer hover:ring-2 ring-primary transition-all"
            onClick={() => {
              const full = localPhotoFull || product?.photo_full || product?.photo_thumb;
              if (full) setFullscreenPhoto(getPhotoUrl(full)!);
            }}
          >
            {localPhotoFull || product?.photo_full || product?.photo_thumb ? (
              <>
                <img
                  key={`full-${photoVersion}`}
                  src={`${getPhotoUrl(localPhotoFull || product?.photo_full || product?.photo_thumb || "")}${photoVersion > 0 ? `?v=${photoVersion}` : ""}`}
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

          {/* Main photo upload button */}
          <Button
            type="button"
            variant="outline"
            className="w-full"
            disabled={uploading || isCreate}
            onClick={() => setUploadFullModal(true)}
          >
            <Camera className="w-4 h-4 mr-2" />
            Загрузить основное фото
          </Button>

          {/* Thumbnail preview + upload */}
          <div className="flex items-center gap-3">
            <div
              className="relative w-20 h-20 shrink-0 bg-muted rounded-lg flex items-center justify-center overflow-hidden cursor-pointer hover:ring-2 ring-primary transition-all"
              onClick={() => {
                const thumb = localPhotoThumb || product?.photo_thumb || product?.photo_full;
                if (thumb) setFullscreenPhoto(getPhotoUrl(thumb)!);
              }}
            >
              {localPhotoThumb || product?.photo_thumb || product?.photo_full ? (
                <>
                  <img
                    key={`thumb-${photoVersion}`}
                    src={`${getPhotoUrl(localPhotoThumb || product?.photo_thumb || product?.photo_full || "")}${photoVersion > 0 ? `?v=${photoVersion}` : ""}`}
                    alt="Preview"
                    className="w-full h-full object-contain pointer-events-none"
                  />
                  <div className="absolute bottom-1 right-1 p-1 bg-black/50 text-white rounded-full pointer-events-none">
                    <Maximize2 className="w-3 h-3" />
                  </div>
                </>
              ) : (
                <Image className="w-6 h-6 text-muted-foreground" />
              )}
            </div>

            <Button
              type="button"
              variant="outline"
              className="flex-1"
              disabled={uploading || isCreate}
              onClick={() => setUploadThumbModal(true)}
            >
              <Camera className="w-4 h-4 mr-2" />
              Загрузить превью
            </Button>
          </div>

          {isCreate && (
            <p className="text-xs text-muted-foreground text-center">
              Фото загружаются после создания товара
            </p>
          )}
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
              <label className="text-sm font-medium">Кол-во на подвесе, шт</label>
              <Input
                type="number"
                className="h-10"
                value={form.quantity_per_hanger ?? ""}
                onChange={(e) => update("quantity_per_hanger", e.target.value ? parseInt(e.target.value) : null)}
              />
            </div>
            <div className="space-y-1 sm:col-start-2">
              <label className="text-sm font-medium">Длины, мм</label>
              <div className="space-y-1">
                <div className="flex gap-2 items-stretch">
                  <Input
                    type="number"
                    placeholder="Введите длину"
                    className="w-32 h-10"
                    value={newLength}
                    onChange={(e) => setNewLength(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        commitLength();
                      }
                    }}
                  />
                  <Button
                    type="button"
                    className="h-10 bg-green-600 hover:bg-green-700"
                    onClick={commitLength}
                  >
                    <Plus className="h-3 w-3 mr-1" />
                    Добавить
                  </Button>
                </div>
                {(form.lengths_mm ?? []).length > 0 ? (
                  <div className="flex flex-wrap gap-2 items-center">
                    {(form.lengths_mm ?? []).map((len, idx) => {
                      return (
                        <div key={`${len}-${idx}`} className="inline-flex items-center gap-1 bg-secondary rounded-md px-2 py-1 text-sm">
                          <span>{len} мм</span>
                          <button
                            type="button"
                            onClick={() => {
                              const vals = (form.lengths_mm ?? []).filter((_, i) => i !== idx);
                              setLengths(vals);
                            }}
                            className="text-muted-foreground hover:text-destructive"
                          >
                            <Minus className="h-3 w-3" />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground">Добавьте хотя бы одну длину.</p>
                )}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <Checkbox
                  id="is_paired_profile"
                  checked={form.is_paired_profile ?? false}
                  onCheckedChange={(checked) => update("is_paired_profile", checked === true)}
                />
                <label htmlFor="is_paired_profile" className="text-sm font-medium leading-none cursor-pointer">
                  Парный профиль
                </label>
              </div>
              <div className="flex items-center gap-2">
                <Checkbox
                  id="skip_shot_blast"
                  checked={form.skip_shot_blast ?? false}
                  onCheckedChange={(checked) => update("skip_shot_blast", checked === true)}
                />
                <label htmlFor="skip_shot_blast" className="text-sm font-medium leading-none cursor-pointer">
                  Не дробеструится
                </label>
              </div>
              <div className="flex items-center gap-2">
                <Checkbox
                  id="is_laminated"
                  checked={form.is_laminated ?? false}
                  onCheckedChange={(checked) => update("is_laminated", checked === true)}
                />
                <label htmlFor="is_laminated" className="text-sm font-medium leading-none cursor-pointer">
                  Ламинируется
                </label>
              </div>
            </div>

            <div className="space-y-1">
              <label className="text-sm font-medium">Эквивалентные артикула</label>
              <ProductSearchMulti
                values={form.aliases || []}
                onChange={(aliases) => update("aliases", aliases)}
                onAliasClick={onAliasClick}
                excludeSku={product?.sku}
                placeholder="Поиск по артикулу"
              />
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
        </div>
      </div>

      <div className="flex justify-between gap-2 pt-2">
        <div>
          {!isCreate && onDelete && (
            <Button type="button" variant="destructive" size="sm" onClick={onDelete}>
              <Trash2 className="w-4 h-4 mr-1" />
              Удалить
            </Button>
          )}
        </div>
        <div className="flex gap-2">
          <Button type="button" variant="outline" onClick={onCancel}>Закрыть</Button>
          <Button type="submit" disabled={uploading}>{isCreate ? "Создать" : "Сохранить"}</Button>
        </div>
      </div>

      <ImageUploadModal
        open={uploadFullModal}
        onOpenChange={setUploadFullModal}
        onFileSelected={(file) => handlePhotoSelect(file, "full")}
        title="Основное фото"
      />
      <ImageUploadModal
        open={uploadThumbModal}
        onOpenChange={setUploadThumbModal}
        onFileSelected={(file) => handlePhotoSelect(file, "thumb")}
        title="Фото превью"
      />
    </form>
  );
});
