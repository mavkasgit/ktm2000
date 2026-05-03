import React, { useEffect, useImperativeHandle, useState, forwardRef } from "react";
import { Image, Maximize2, Camera, Trash2 } from "lucide-react";
import { Button } from "@/shared/ui/Button";
import { Input } from "@/shared/ui/Input";
import { Checkbox } from "@/shared/ui/Checkbox";
import { FullscreenPhoto } from "./FullscreenPhoto";
import { ImageUploadModal } from "./ImageUploadModal";
import { ProductSearchMulti } from "./ProductSearchMulti";
import { getPhotoUrl } from "./getPhotoUrl";
import { uploadProductPhoto } from "@/shared/api/products";
import type { Product, ProductType, CreateProductInput, PatchProductInput } from "@/shared/api/products";

const TYPE_OPTIONS: { value: ProductType; label: string }[] = [
  { value: "finished_good", label: "Готовая продукция" },
  { value: "semi_finished", label: "Полуфабрикат" },
  { value: "component", label: "Сырье" },
  { value: "material", label: "Материал" },
];

export type DialogMode = "create" | "edit";

function isFormDirty(form: CreateProductInput, product: Product | null, isCreate: boolean): boolean {
  if (isCreate) {
    return (
      form.sku !== "" ||
      form.name !== "" ||
      form.type !== "finished_good" ||
      form.unit !== "шт" ||
      (form.is_active ?? true) !== true ||
      form.notes != null ||
      form.profile_type != null ||
      form.alloy != null ||
      form.color != null ||
      form.anod_type != null ||
      form.length_mm != null ||
      form.weight_per_meter != null ||
      form.quantity_per_hanger != null ||
      form.cross_section != null ||
      (form.is_paired_profile ?? false) !== false ||
      (form.skip_shot_blast ?? false) !== false ||
      (form.aliases?.length ?? 0) > 0
    );
  }
  if (!product) return false;
  return (
    form.name !== product.name ||
    form.type !== product.type ||
    form.unit !== product.unit ||
    form.is_active !== product.is_active ||
    form.notes !== product.notes ||
    form.profile_type !== product.profile_type ||
    form.alloy !== product.alloy ||
    form.color !== product.color ||
    form.anod_type !== product.anod_type ||
    form.length_mm !== product.length_mm ||
    form.weight_per_meter !== product.weight_per_meter ||
    form.quantity_per_hanger !== product.quantity_per_hanger ||
    form.cross_section !== product.cross_section ||
    form.is_paired_profile !== product.is_paired_profile ||
    form.skip_shot_blast !== product.skip_shot_blast ||
    JSON.stringify(form.aliases ?? []) !== JSON.stringify(product.aliases ?? [])
  );
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
}>(function CatalogForm({
  product,
  mode,
  onSave,
  onCancel,
  onDelete,
  onAliasClick,
  onDirtyChange,
}, ref) {
  const isCreate = mode === "create";
  const [fullscreenPhoto, setFullscreenPhoto] = useState<string | null>(null);
  const [localPhotoFull, setLocalPhotoFull] = useState<string | null>(null);
  const [localPhotoThumb, setLocalPhotoThumb] = useState<string | null>(null);
  const [uploadFullModal, setUploadFullModal] = useState(false);
  const [uploadThumbModal, setUploadThumbModal] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [photoVersion, setPhotoVersion] = useState(0);
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
    skip_shot_blast: product?.skip_shot_blast ?? false,
    aliases: product?.aliases ?? [],
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

  useImperativeHandle(ref, () => ({
    save: () => {
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
    },
  }));

  const update = <K extends keyof CreateProductInput>(key: K, value: CreateProductInput[K]) => {
    setForm((f) => ({ ...f, [key]: value }));
  };

  const isDirty = isFormDirty(form, product, isCreate);
  useEffect(() => {
    onDirtyChange?.(isDirty);
  }, [isDirty, onDirtyChange]);

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
                  src={`${getPhotoUrl(localPhotoFull || product?.photo_full || product?.photo_thumb)!}${photoVersion > 0 ? `?v=${photoVersion}` : ""}`}
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
                    src={`${getPhotoUrl(localPhotoThumb || product?.photo_thumb || product?.photo_full)!}${photoVersion > 0 ? `?v=${photoVersion}` : ""}`}
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
              <Input type="number" value={form.quantity_per_hanger ?? ""} onChange={(e) => update("quantity_per_hanger", e.target.value ? parseInt(e.target.value) : null)} />
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium">Длина, мм</label>
              <Input type="number" step="0.1" value={form.length_mm ?? ""} onChange={(e) => update("length_mm", e.target.value ? parseFloat(e.target.value) : null)} />
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
