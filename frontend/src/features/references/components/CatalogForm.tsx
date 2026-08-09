import React, { useEffect, useImperativeHandle, useState, forwardRef, useCallback, useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { Image, Maximize2, Camera, Trash2, Plus, ChevronDown, ChevronUp } from "lucide-react";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";
import { Checkbox } from "@/shared/ui/checkbox";
import { FullscreenPhoto } from "./FullscreenPhoto";
import { ImageUploadModal } from "./ImageUploadModal";
import { ProductSearchMulti } from "./ProductSearchMulti";
import { ProductDimensionsSection, type ProductDimensionsSectionHandle } from "./ProductDimensionsSection";
import { getPhotoUrl } from "./getPhotoUrl";
import { uploadProductPhoto, getErrorMessage } from "@/shared/api/products";
import { listDimensionTypes } from "../api";
import { queryKeys } from "@/shared/api/queryKeys";
import { calcHanger, type HangerCalcResult } from "@/shared/api/hangerCalc";
import { isHangerAutoMode, lengthKey, manualByLength, normalizeLengths, primaryLength, productLengths } from "@/shared/lib/hangerQuantity";
import { parseNumericInput } from "@/shared/lib/parseNumericInput";
import { isLengthState } from "@/shared/lib/dimensionState";
import { RadioGroup, RadioGroupItem } from "@/shared/ui/radio-group";
import { cn } from "@/shared/utils/cn";
import type { Product, CreateProductInput, PatchProductInput, QuantityPerHangerDict, DimensionState } from "@/shared/api/products";

export type DialogMode = "create" | "edit";

export type FieldChange = { field: string; label: string; from: string | number | boolean | null; to: string | number | boolean | null };

/** Сравнение значений для diff/patch (JSON-нормализация). */
function eq(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/** Словарь формы: только manual-значения (auto считается сервером, #60). */
function manualDictFromProduct(product: Product | null): QuantityPerHangerDict | null {
  if (!product?.quantity_per_hanger) return null;
  const result: QuantityPerHangerDict = {};
  for (const [key, entry] of Object.entries(product.quantity_per_hanger)) {
    result[key] = { auto: null, manual: entry?.manual ?? null };
  }
  return result;
}

/**
 * Мерж manual-значений формы с продуктовыми: форма явно задаёт ключ —
 * берём её manual (в т.ч. null = очистить). Ключи, которых нет в форме,
 * берутся из продукта (#65: очистка manual в ручном режиме работает).
 */
function mergedManuals(
  formDict: QuantityPerHangerDict | null,
  productDict: QuantityPerHangerDict | null,
): Record<string, number | null> {
  const merged: Record<string, number | null> = { ...manualByLength(productDict) };
  for (const [key, entry] of Object.entries(formDict ?? {})) {
    merged[key] = entry?.manual ?? null;
  }
  return merged;
}

/** Diff manual-значений для списка изменений: {from, to} в виде «2780 мм: 72». */
function manualChangeTexts(
  formDict: QuantityPerHangerDict | null,
  productDict: QuantityPerHangerDict | null,
): { from: string; to: string } | null {
  const productManuals = manualByLength(productDict);
  const merged = mergedManuals(formDict, productDict);
  const keys = [...new Set([...Object.keys(productManuals), ...Object.keys(merged)])]
    .sort((a, b) => Number(a) - Number(b));
  const changed = keys.filter((k) => (productManuals[k] ?? null) !== (merged[k] ?? null));
  if (changed.length === 0) return null;
  const fmt = (m: Record<string, number | null>) =>
    changed.map((k) => `${k} мм: ${m[k] ?? "—"}`).join("; ");
  return { from: fmt(productManuals), to: fmt(merged) };
}

/** Payload-словарь {length: {auto: null, manual}} для всех длин формы. */
function buildManualPayloadDict(
  lengths: number[],
  merged: Record<string, number | null>,
): QuantityPerHangerDict {
  const dict: QuantityPerHangerDict = {};
  for (const length of lengths) {
    const key = lengthKey(length);
    dict[key] = { auto: null, manual: merged[key] ?? null };
  }
  return dict;
}

function buildInitialForm(product: Product | null, mode: DialogMode): CreateProductInput {
  const lengths = productLengths(product ?? {});
  return {
    sku: product?.sku ?? "",
    code: product?.code ?? null,
    name: product?.name ?? "",
    type: product?.type ?? (mode === "create" ? "component" : "finished_good"),
    unit: product?.unit ?? "шт",
    is_active: product?.is_active ?? true,
    notes: product?.notes ?? null,
    profile_type: product?.profile_type ?? null,
    alloy: product?.alloy ?? null,
    color: product?.color ?? null,
    anod_type: product?.anod_type ?? null,
    length_mm: lengths[0] ?? product?.length_mm ?? null,
    primary_length_mm: product?.primary_length_mm ?? lengths[0] ?? null,
    weight_per_meter: product?.weight_per_meter ?? null,
    perimeter_mm: product?.perimeter_mm ?? null,
    mount_width_mm: product?.mount_width_mm ?? null,
    quantity_per_hanger: manualDictFromProduct(product),
    cross_section: product?.cross_section ?? null,
    is_paired_profile: product?.is_paired_profile ?? false,
    skip_shot_blast: product?.skip_shot_blast ?? false,
    dimension_state: product?.dimension_state ?? "length",
    aliases: product?.aliases ?? [],
    lengths_mm: lengths,
    is_laminated: product?.is_laminated ?? false,
  };
}

function getChanges(form: CreateProductInput, product: Product | null, isCreate: boolean): FieldChange[] {
  if (isCreate || !product) return [];
  const changes: FieldChange[] = [];
  const formLengths = normalizeLengths(form.lengths_mm ?? []);
  const productLens = productLengths(product);

  if (!eq(form.sku, product.sku)) changes.push({ field: "sku", label: "Артикул", from: product.sku, to: form.sku ?? "" });
  if (!eq(form.code, product.code)) changes.push({ field: "code", label: "Уникальный код", from: product.code ?? "—", to: form.code ?? "—" });
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
  if (!eq(form.perimeter_mm ?? null, product.perimeter_mm ?? null)) changes.push({ field: "perimeter_mm", label: "Периметр, мм", from: product.perimeter_mm ?? "—", to: form.perimeter_mm ?? "—" });
  if (!eq(form.mount_width_mm ?? null, product.mount_width_mm ?? null)) changes.push({ field: "mount_width_mm", label: "Габарит, мм", from: product.mount_width_mm ?? "—", to: form.mount_width_mm ?? "—" });
  const manualDiff = manualChangeTexts(form.quantity_per_hanger ?? null, product.quantity_per_hanger ?? null);
  if (manualDiff) changes.push({ field: "quantity_per_hanger", label: "Кол-во на подвесе", from: manualDiff.from, to: manualDiff.to });
  if (!eq(form.cross_section, product.cross_section)) changes.push({ field: "cross_section", label: "Сечение", from: product.cross_section ?? "—", to: form.cross_section ?? "—" });
  if (!eq(form.is_paired_profile, product.is_paired_profile)) changes.push({ field: "is_paired_profile", label: "Парный профиль", from: product.is_paired_profile ? "Да" : "Нет", to: form.is_paired_profile ? "Да" : "Нет" });
  if (!eq(form.skip_shot_blast, product.skip_shot_blast)) changes.push({ field: "skip_shot_blast", label: "Не дробеструится", from: product.skip_shot_blast ? "Да" : "Нет", to: form.skip_shot_blast ? "Да" : "Нет" });
  if (!eq(form.aliases ?? [], product.aliases ?? [])) changes.push({ field: "aliases", label: "Эквиваленты", from: (product.aliases ?? []).join(", ") || "—", to: (form.aliases ?? []).join(", ") || "—" });
  if (!eq(formLengths, productLens)) changes.push({ field: "lengths_mm", label: "Длины", from: productLens.join(", ") || "—", to: formLengths.join(", ") || "—" });
  const formPrimary = form.primary_length_mm ?? null;
  const productPrimary = product.primary_length_mm ?? productLengths(product)[0] ?? null;
  if (!eq(formPrimary, productPrimary)) {
    changes.push({
      field: "primary_length_mm",
      label: "Основная длина",
      from: productPrimary != null ? `${productPrimary} мм` : "—",
      to: formPrimary != null ? `${formPrimary} мм` : "—",
    });
  }
  if (!eq(form.is_laminated ?? false, product.is_laminated)) changes.push({ field: "is_laminated", label: "Ламинируется", from: product.is_laminated ? "Да" : "Нет", to: form.is_laminated ? "Да" : "Нет" });
  if (!eq(form.dimension_state ?? "length", product.dimension_state ?? "length")) changes.push({ field: "dimension_state", label: "Размерность", from: product.dimension_state ?? "length", to: form.dimension_state ?? "length" });
  return changes;
}

export interface CatalogFormRef {
  save: () => void;
}

type HangerPreviewState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; results: HangerCalcResult[] | null }
  | { status: "error"; message: string };

export const CatalogForm = forwardRef<CatalogFormRef, {
  product: Product | null;
  mode: DialogMode;
  onSave: (payload: CreateProductInput | PatchProductInput, mode: DialogMode) => void;
  onCancel: () => void;
  onDelete?: () => void;
  onAliasClick?: (sku: string) => void;
  onDirtyChange?: (dirty: boolean) => void;
  onChangesChange?: (changes: FieldChange[]) => void;
  readOnly?: boolean;
}>(function CatalogForm({
  product,
  mode,
  onSave,
  onCancel,
  onDelete,
  onAliasClick,
  onDirtyChange,
  onChangesChange,
  readOnly = false,
}, ref) {
  const isCreate = mode === "create";
  const [fullscreenPhoto, setFullscreenPhoto] = useState<string | null>(null);
  const handleCloseFullscreen = useCallback(() => {
    setFullscreenPhoto(null);
  }, []);
  const [localPhotoFull, setLocalPhotoFull] = useState<string | null>(null);
  const [localPhotoThumb, setLocalPhotoThumb] = useState<string | null>(null);
  const [uploadFullModal, setUploadFullModal] = useState(false);
  const [uploadThumbModal, setUploadThumbModal] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [photoVersion, setPhotoVersion] = useState(0);
  const [newLength, setNewLength] = useState("");
  const [form, setForm] = useState<CreateProductInput>(() => buildInitialForm(product, mode));
  const [hangerPreview, setHangerPreview] = useState<HangerPreviewState>({ status: "idle" });
  const [changesOpen, setChangesOpen] = useState(false);
  const notesRef = useRef<HTMLTextAreaElement | null>(null);
  const dimsRef = useRef<ProductDimensionsSectionHandle>(null);

  const { data: dimensionTypes = [] } = useQuery({
    queryKey: queryKeys.dimensions.types(),
    queryFn: listDimensionTypes,
  });
  const resizeNotes = useCallback(() => {
    const el = notesRef.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = `${el.scrollHeight}px`;
  }, []);
  useEffect(() => {
    resizeNotes();
  }, [form.notes, resizeNotes]);

  useEffect(() => {
    setForm(buildInitialForm(product, mode));
    setLocalPhotoFull(null);
    setLocalPhotoThumb(null);
    setPhotoVersion(0);
    setNewLength("");
    setHangerPreview({ status: "idle" });
    setChangesOpen(false);
  }, [product?.id, mode]);

  const formLengths = useMemo(() => normalizeLengths(form.lengths_mm ?? []), [form.lengths_mm]);
  const autoMode = isHangerAutoMode(form);

  useEffect(() => {
    if (!autoMode || formLengths.length === 0) {
      setHangerPreview({ status: "idle" });
      return;
    }
    const perimeter = form.perimeter_mm ?? null;
    const mountWidth = form.mount_width_mm ?? null;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setHangerPreview({ status: "loading" });
      calcHanger(
        formLengths.map((length) => ({
          perimeter_mm: perimeter,
          mount_width_mm: mountWidth,
          length_mm: length,
        })),
      )
        .then((resp) => {
          if (!cancelled) setHangerPreview({ status: "ready", results: resp.results });
        })
        .catch((e) => {
          if (!cancelled) setHangerPreview({ status: "error", message: getErrorMessage(e) });
        });
    }, 400);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [autoMode, form.perimeter_mm, form.mount_width_mm, formLengths]);

  const autoQuantityFor = (length: number): number | null => {
    if (hangerPreview.status !== "ready" || !hangerPreview.results) return null;
    const idx = formLengths.indexOf(length);
    const result = idx >= 0 ? hangerPreview.results[idx] : null;
    return result?.is_calculable ? result.total : null;
  };
  const manualForLength = (length: number): number | null =>
    form.quantity_per_hanger?.[lengthKey(length)]?.manual ?? null;

  const updateManualForLength = (length: number, value: number | null) => {
    const key = lengthKey(length);
    setForm((f) => ({
      ...f,
      quantity_per_hanger: {
        ...(f.quantity_per_hanger ?? {}),
        [key]: { auto: null, manual: value },
      },
    }));
  };

  const setLengths = useCallback((values: number[]) => {
    const normalized = normalizeLengths(values);
    setForm((f) => {
      const currentPrimary = f.primary_length_mm;
      const primary =
        currentPrimary != null && normalized.includes(currentPrimary)
          ? currentPrimary
          : normalized[0] ?? null;
      return {
        ...f,
        lengths_mm: normalized,
        primary_length_mm: primary,
        // Keep legacy scalar field in sync with the first length.
        length_mm: normalized[0] ?? null,
      };
    });
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
    const formLengths = normalizeLengths(form.lengths_mm ?? []);
    const productLens = productLengths(product);
    const formPrimaryLength = formLengths[0] ?? null;
    const productPrimaryLength = productLens[0] ?? (product.length_mm ?? null);

    if (!eq(form.sku, product.sku)) patch.sku = form.sku.trim();
    if (!eq(form.code, product.code)) patch.code = form.code?.trim() || null;
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
    if (!eq(form.perimeter_mm ?? null, product.perimeter_mm ?? null)) patch.perimeter_mm = form.perimeter_mm ?? null;
    if (!eq(form.mount_width_mm ?? null, product.mount_width_mm ?? null)) patch.mount_width_mm = form.mount_width_mm ?? null;
    const merged = mergedManuals(form.quantity_per_hanger ?? null, product.quantity_per_hanger ?? null);
    if (!eq(merged, manualByLength(product.quantity_per_hanger ?? null))) {
      patch.quantity_per_hanger = buildManualPayloadDict(formLengths, merged);
    }
    if (!eq(form.cross_section, product.cross_section)) patch.cross_section = form.cross_section;
    if (!eq(form.is_paired_profile, product.is_paired_profile)) patch.is_paired_profile = form.is_paired_profile;
    if (!eq(form.skip_shot_blast, product.skip_shot_blast)) patch.skip_shot_blast = form.skip_shot_blast;
    if (!eq(form.aliases ?? [], product.aliases ?? [])) patch.aliases = form.aliases;
    if (!eq(formLengths, productLens)) patch.lengths_mm = formLengths;
    const formPrimary = form.primary_length_mm ?? null;
    const productPrimary = product.primary_length_mm ?? productLengths(product)[0] ?? null;
    if (!eq(formPrimary, productPrimary)) patch.primary_length_mm = formPrimary;
    if (!eq(form.is_laminated ?? false, product.is_laminated)) patch.is_laminated = form.is_laminated;
    if (!eq(form.dimension_state ?? "length", product.dimension_state ?? "length")) patch.dimension_state = form.dimension_state;
    return patch;
  }, [form, product]);

  const doSave = async () => {
    await dimsRef.current?.flushPending();
    if (isCreate) {
      onSave(form, mode);
    } else if (product) {
      onSave(buildPatch(), mode);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    doSave();
  };

  useImperativeHandle(ref, () => ({
    save: () => { doSave(); },
  }), [form, product, isCreate, mode, onSave, buildPatch]);

  const update = <K extends keyof CreateProductInput>(key: K, value: CreateProductInput[K]) => {
    setForm((f) => ({ ...f, [key]: value }));
  };

  const changes = useMemo(() => getChanges(form, product, isCreate), [form, product, isCreate]);
  const isDirty = changes.length > 0;

  const perimeterInvalid = form.perimeter_mm != null && !(form.perimeter_mm > 0);
  const mountWidthInvalid = form.mount_width_mm != null && !(form.mount_width_mm > 0);
  const quantityInvalid =
    !autoMode && formLengths.some((len) => {
      const m = manualForLength(len);
      return m != null && !(m > 0);
    });
  const hasValidationErrors = perimeterInvalid || mountWidthInvalid || quantityInvalid;

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
          onClose={handleCloseFullscreen}
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
            disabled={uploading || isCreate || readOnly}
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
              disabled={uploading || isCreate || readOnly}
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
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="space-y-1">
              <label className="text-sm font-medium">Артикул</label>
              <Input
                value={form.sku}
                onChange={(e) => update("sku", e.target.value)}
                disabled={readOnly}
                readOnly={false}
                autoComplete="off"
                spellCheck={false}
                placeholder="ЮП-1234"
              />
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium">Наименование</label>
              <Input value={form.name} onChange={(e) => update("name", e.target.value)} disabled={readOnly} placeholder="Полное название" />
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium">Уникальный код</label>
              <Input
                value={form.code ?? ""}
                onChange={(e) => update("code", e.target.value || null)}
                disabled={readOnly}
                autoComplete="off"
                spellCheck={false}
              />
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium">Эквивалентные артикула</label>
              <ProductSearchMulti
                values={form.aliases || []}
                onChange={(aliases) => update("aliases", aliases)}
                onAliasClick={onAliasClick}
                excludeSku={form.sku || product?.sku}
                showPairedStatus={false}
                disabled={readOnly}
              />
            </div>
            <div className="space-y-2 self-start pt-[22px]">
              <div className="flex items-center gap-2">
                <Checkbox
                  id="is_paired_profile"
                  checked={form.is_paired_profile ?? false}
                  onCheckedChange={(checked) => update("is_paired_profile", checked === true)}
                  disabled={readOnly}
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
                  disabled={readOnly}
                />
                <label htmlFor="skip_shot_blast" className="text-sm font-medium leading-none cursor-pointer">
                  Не дробеструится
                </label>
              </div>
            </div>
            <div className="flex items-center gap-2 self-start pt-[22px]">
              <Checkbox
                id="is_laminated"
                checked={form.is_laminated ?? false}
                onCheckedChange={(checked) => update("is_laminated", checked === true)}
                disabled={readOnly}
              />
              <label htmlFor="is_laminated" className="text-sm font-medium leading-none cursor-pointer">
                Ламинируется
              </label>
            </div>
          </div>

          <div className="rounded-lg border bg-muted/20 p-3 space-y-3">
            <div className="flex flex-wrap items-end gap-3">
              <div className="space-y-1 flex-1 min-w-[200px]">
                <ProductDimensionsSection
                  ref={dimsRef}
                  productId={product?.id}
                  dimensionState={form.dimension_state ?? "length"}
                  onDimensionStateChange={(state: DimensionState) => update("dimension_state", state)}
                  dimensionTypes={dimensionTypes}
                  readOnly={readOnly}
                />
                {isLengthState(form.dimension_state) && (
                  <div className="flex gap-2 items-stretch">
                    <Input
                      type="number"
                      placeholder="Введите длину"
                      className="h-10 flex-1"
                      value={newLength}
                      onChange={(e) => setNewLength(e.target.value)}
                      disabled={readOnly}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          commitLength();
                        }
                      }}
                    />
                    <Button
                      type="button"
                      className="h-10 bg-green-600 hover:bg-green-700 shrink-0"
                      onClick={commitLength}
                      disabled={readOnly}
                    >
                      <Plus className="h-3 w-3 mr-1" />
                      Добавить
                    </Button>
                  </div>
                )}
              </div>
              {isLengthState(form.dimension_state) && (
                <>
                  <div className="space-y-1 shrink-0">
                    <label className="text-sm font-medium">Периметр, мм</label>
                    <Input
                      type="number"
                      step="0.1"
                      className={cn(
                        "h-10 w-[100px]",
                        perimeterInvalid && "border-destructive focus-visible:ring-destructive",
                        !perimeterInvalid && (form.perimeter_mm ?? null) == null && "bg-amber-50 border-amber-300",
                        !perimeterInvalid && (form.perimeter_mm ?? null) != null && "bg-emerald-50 border-emerald-300",
                      )}
                      value={form.perimeter_mm ?? ""}
                      onChange={(e) => update("perimeter_mm", parseNumericInput(e.target.value))}
                      disabled={readOnly}
                    />
                    {perimeterInvalid && (
                      <p className="text-xs text-destructive">Значение должно быть больше 0</p>
                    )}
                  </div>
                  <div className="space-y-1 shrink-0">
                    <label className="text-sm font-medium">Габарит, мм</label>
                    <Input
                      type="number"
                      step="0.1"
                      className={cn(
                        "h-10 w-[100px]",
                        mountWidthInvalid && "border-destructive focus-visible:ring-destructive",
                        !mountWidthInvalid && (form.mount_width_mm ?? null) == null && "bg-amber-50 border-amber-300",
                        !mountWidthInvalid && (form.mount_width_mm ?? null) != null && "bg-emerald-50 border-emerald-300",
                      )}
                      value={form.mount_width_mm ?? ""}
                      onChange={(e) => update("mount_width_mm", parseNumericInput(e.target.value))}
                      disabled={readOnly}
                    />
                    {mountWidthInvalid && (
                      <p className="text-xs text-destructive">Значение должно быть больше 0</p>
                    )}
                  </div>
                </>
              )}
            </div>

            {isLengthState(form.dimension_state) ? (
              <>
                <div className="flex items-start gap-4">
                  <div className="rounded-md border bg-background overflow-hidden inline-block min-w-0 shrink-0">
                    <table className="text-sm">
                      <thead>
                        <tr className="bg-muted/50 text-xs text-muted-foreground">
                          <th className="text-left font-medium px-3 py-2">
                            {readOnly ? "Основная" : "Основная (радио)"}
                          </th>
                          <th className="text-left font-medium px-3 py-2">Кол-во на подвесе, шт</th>
                          <th className="text-left font-medium px-3 py-2">Длина, мм</th>
                        </tr>
                      </thead>
                      <tbody>
                        <RadioGroup
                          value={form.primary_length_mm != null ? String(form.primary_length_mm) : undefined}
                          onValueChange={(val) => update("primary_length_mm", Number(val))}
                          disabled={readOnly}
                        >
                          {formLengths.map((len, idx) => {
                            const rowManual = manualForLength(len);
                            const rowInvalid = !autoMode && rowManual != null && !(rowManual > 0);
                            return (
                              <tr key={len} className="border-t">
                                <td className="px-3 py-1.5">
                                  <RadioGroupItem value={String(len)} id={`primary-${len}`} />
                                </td>
                                <td className="px-3 py-1.5">
                                  <div className="flex items-center gap-2">
                                    <Input
                                      type="number"
                                      className={cn(
                                        "h-9 w-28",
                                        rowInvalid && "border-destructive focus-visible:ring-destructive",
                                        !rowInvalid && autoMode && "bg-emerald-50 border-emerald-300",
                                        !rowInvalid && !autoMode && "bg-amber-50 border-amber-300",
                                      )}
                                      value={autoMode ? autoQuantityFor(len) ?? "" : rowManual ?? ""}
                                      placeholder={autoMode ? "—" : ""}
                                      readOnly={autoMode}
                                      onChange={(e) => {
                                        const parsed = parseNumericInput(e.target.value);
                                        updateManualForLength(len, parsed == null ? null : Math.trunc(parsed));
                                      }}
                                      disabled={readOnly}
                                      title={autoMode ? "В авто-режиме значение считается из периметра и габарита" : undefined}
                                    />
                                    {autoMode && (
                                      <span className="text-xs font-medium text-emerald-700 whitespace-nowrap">авто</span>
                                    )}
                                  </div>
                                </td>
                                <td className="px-3 py-1.5">
                                  <div className="flex items-center gap-2">
                                    <label htmlFor={`primary-${len}`} className={cn("cursor-pointer", form.primary_length_mm === len && "font-semibold")}>
                                      {len}
                                    </label>
                                  </div>
                                </td>
                                {!readOnly && (
                                  <td className="px-2 py-1.5 text-right">
                                    <button
                                      type="button"
                                      onClick={() => {
                                        const vals = (form.lengths_mm ?? []).filter((_, i) => i !== idx);
                                        setLengths(vals);
                                      }}
                                      className="text-muted-foreground hover:text-destructive"
                                      title="Удалить длину"
                                    >
                                      <Trash2 className="h-4 w-4" />
                                    </button>
                                  </td>
                                )}
                              </tr>
                            );
                          })}
                        </RadioGroup>
                      </tbody>
                    </table>
                    {formLengths.length === 0 && (
                      <p className="px-3 py-2 text-xs text-muted-foreground">Добавьте хотя бы одну длину.</p>
                    )}
                  </div>
                </div>

                {hangerPreview.status === "error" ? (
                  <p className="text-xs text-destructive">{hangerPreview.message}</p>
                ) : autoMode && hangerPreview.status === "loading" ? (
                  <p className="text-xs text-muted-foreground">Расчёт…</p>
                ) : autoMode && hangerPreview.status === "ready" ? (
                  <p className="text-xs text-muted-foreground">
                    Значения рассчитаны из периметра и габарита.
                    {formLengths.length > 0 && ` Основная длина ${form.primary_length_mm ?? formLengths[0]} мм → ${autoQuantityFor(form.primary_length_mm ?? formLengths[0]) ?? "—"} шт.`}
                  </p>
                ) : autoMode ? (
                  <p className="text-xs text-muted-foreground">
                    Значения рассчитаны из периметра и габарита.
                  </p>
                ) : null}
                {quantityInvalid && (
                  <p className="text-xs text-destructive">Значение должно быть больше 0</p>
                )}
              </>
            ) : (
              <p className="text-xs text-muted-foreground">
                Кол-во на подвесе не настраивается для 2D/3D-размерности.
              </p>
            )}
          </div>

          <div className="space-y-1">
            <label className="text-sm font-medium">Примечания</label>
            <textarea
              ref={notesRef}
              className="w-full min-h-[40px] resize-none rounded-md border border-input bg-background px-3 py-2 text-sm overflow-hidden"
              value={form.notes ?? ""}
              onChange={(e) => update("notes", e.target.value || null)}
              placeholder="Дополнительная информация..."
              disabled={readOnly}
            />
          </div>
        </div>
      </div>

      <div className="flex justify-between gap-2 pt-2">
        <div>
          {!isCreate && onDelete && !readOnly && (
            <Button type="button" variant="destructive" size="sm" onClick={onDelete}>
              <Trash2 className="w-4 h-4 mr-1" />
              Удалить
            </Button>
          )}
        </div>
        <div className="relative flex gap-2 items-center">
          {!isCreate && !readOnly && changes.length > 0 && (
            <>
              <button
                type="button"
                onClick={() => setChangesOpen((o) => !o)}
                className="inline-flex items-center gap-1 text-xs text-blue-800 bg-blue-50 border border-blue-200 rounded-md px-2 py-1 hover:bg-blue-100 transition-colors"
              >
                {changesOpen ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                Изменено: {changes.length}
              </button>
              {changesOpen && (
                <div className="absolute right-0 bottom-full mb-2 w-96 max-w-[80vw] bg-blue-50 border border-blue-200 rounded-lg p-3 shadow-lg">
                  <p className="text-sm font-medium text-blue-900 mb-1">Изменения:</p>
                  <ul className="text-xs text-blue-800 space-y-0.5 max-h-56 overflow-auto">
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
            </>
          )}
          <Button type="button" variant="outline" onClick={onCancel}>Закрыть</Button>
          {!readOnly && (
            <Button type="submit" disabled={uploading || hasValidationErrors}>{isCreate ? "Создать" : "Сохранить"}</Button>
          )}
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
