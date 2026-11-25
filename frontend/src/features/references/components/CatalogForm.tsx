import React, { useEffect, useImperativeHandle, useState, forwardRef, useCallback, useMemo, useRef } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Image, Maximize2, Camera, Trash2, Plus, ChevronDown, ChevronUp } from "lucide-react";
import { Badge } from "@/shared/ui/badge";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";
import { Checkbox } from "@/shared/ui/checkbox";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/shared/ui/alert-dialog";
import { FullscreenPhoto } from "./FullscreenPhoto";
import { ImageUploadModal } from "./ImageUploadModal";
import { ProductSearchMulti } from "./ProductSearchMulti";
import { ProductDimensionsSection, type ProductDimensionsSectionHandle } from "./ProductDimensionsSection";
import { ProductPairsSection } from "./ProductPairsSection";
import { productPhotoUrl } from "./productPhotoUrl";
import { deleteProductPhoto, uploadProductPhoto, getErrorMessage } from "@/shared/api/products";
import { listDimensionTypes } from "../api";
import { queryKeys } from "@/shared/api/queryKeys";
import { calcHanger, type HangerCalcResult } from "@/shared/api/hangerCalc";
import { isHangerAutoMode, isSheetState, lengthKey, manualByLength, normalizeLengths, orphanNormKeys, primaryLength, productLengths, effectiveRawLength } from "@/shared/lib/hangerQuantity";
import { parseNumericInput } from "@/shared/lib/parseNumericInput";
import { isLengthState } from "@/shared/lib/dimensionState";
import { RadioGroup, RadioGroupItem } from "@/shared/ui/radio-group";
import { cn } from "@/shared/utils/cn";
import type { Product, ProductLength, CreateProductInput, PatchProductInput, QuantityPerHangerDict, DimensionState, HangerMode, ThirdPartyPack } from "@/shared/api/products";

/** Ключ ручной нормы объёмного артикула без длины (ADR-0075). */
const DEFAULT_HANGER_KEY = "default";

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
  const keyLabel = (key: string) => (key === DEFAULT_HANGER_KEY ? "по умолчанию" : `${key} мм`);
  const fmt = (m: Record<string, number | null>) =>
    changed.map((k) => `${keyLabel(k)}: ${m[k] ?? "—"}`).join("; ");
  return { from: fmt(productManuals), to: fmt(merged) };
}

/**
 * Payload-словарь {length: {auto: null, manual}} для всех длин формы.
 * `extraKeys` — ключи норм вне реестра (ADR-0047): их правкой нельзя
 * молча пожертвовать значением, поэтому удаление уходит явным null.
 */
function buildManualPayloadDict(
  lengths: Array<number | ProductLength>,
  merged: Record<string, number | null>,
  extraKeys: string[] = [],
): QuantityPerHangerDict {
  const dict: QuantityPerHangerDict = {};
  for (const length of lengths) {
    const key = lengthKey(typeof length === "number" ? length : length.length_mm);
    dict[key] = { auto: null, manual: merged[key] ?? null };
  }
  for (const key of extraKeys) {
    dict[key] = { auto: null, manual: merged[key] ?? null };
  }
  return dict;
}

function lengthsFromProduct(product: Product | null): ProductLength[] {
  return (product?.lengths ?? []).map((length) => ({ ...length }));
}

/**
 * Обнулить ручные нормы длин, снятых из реестра (ADR-0047): ключ остаётся
 * в словаре с manual=null, чтобы правка ушла явным снятием значения, а не
 * молчаливым исчезновением вместе с длиной. Ключи вне реестра не трогаем —
 * их снимает оператор кнопкой в предупреждении, иначе правка длин стирала бы
 * чужой ручной ввод.
 */
function clearNormsOfRemovedLengths(
  dict: QuantityPerHangerDict | null | undefined,
  previousLengths: number[],
  keptLengths: number[],
): QuantityPerHangerDict | null {
  if (!dict) return dict ?? null;
  const kept = new Set(keptLengths.map(lengthKey));
  const removed = previousLengths.map(lengthKey).filter((key) => !kept.has(key));
  const result: QuantityPerHangerDict = { ...dict };
  for (const key of removed) result[key] = { auto: null, manual: null };
  return result;
}

/** Подписи режима подвеса (#126) для списка изменений. */
const HANGER_MODE_LABELS: Record<HangerMode, string> = {
  auto: "Авто",
  manual: "Вручную",
};

function buildInitialForm(product: Product | null, mode: DialogMode): CreateProductInput {
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
    weight_per_meter: product?.weight_per_meter ?? null,
    perimeter_mm: product?.perimeter_mm ?? null,
    mount_width_mm: product?.mount_width_mm ?? null,
    quantity_per_hanger: manualDictFromProduct(product),
    hanger_mode: product?.hanger_mode ?? "manual",
    cross_section: product?.cross_section ?? null,
    skip_shot_blast: product?.skip_shot_blast ?? false,
    dimension_state: product?.dimension_state ?? "length",
    aliases: product?.aliases ?? [],
    lengths: lengthsFromProduct(product),
    is_laminated: product?.is_laminated ?? false,
    third_party: product?.third_party ?? false,
    customer: product?.customer ?? null,
    pack: product?.pack ?? null,
  };
}

/** Норма комплекта: 4 × 2 = 8 шт; null, если числа неположительные. */
function packNorm(pack: ThirdPartyPack | null | undefined): number | null {
  if (!pack || pack.sets_per_hanger <= 0 || pack.pieces_per_set <= 0) return null;
  return pack.sets_per_hanger * pack.pieces_per_set;
}

/** Комплект для списка изменений: «4 × 2 = 8 шт». */
function packText(pack: ThirdPartyPack | null | undefined): string {
  if (!pack) return "—";
  return `${pack.sets_per_hanger} × ${pack.pieces_per_set} = ${pack.sets_per_hanger * pack.pieces_per_set} шт`;
}

function getChanges(form: CreateProductInput, product: Product | null, isCreate: boolean): FieldChange[] {
  if (isCreate || !product) return [];
  const changes: FieldChange[] = [];
  const formLengths = productLengths(form);
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
  if (!eq(form.hanger_mode ?? "auto", product.hanger_mode ?? "auto")) {
    changes.push({
      field: "hanger_mode",
      label: "Режим подвеса",
      from: HANGER_MODE_LABELS[product.hanger_mode ?? "auto"],
      to: HANGER_MODE_LABELS[form.hanger_mode ?? "auto"],
    });
  }
  if (!eq(form.cross_section, product.cross_section)) changes.push({ field: "cross_section", label: "Сечение", from: product.cross_section ?? "—", to: form.cross_section ?? "—" });
  if (!eq(form.skip_shot_blast, product.skip_shot_blast)) changes.push({ field: "skip_shot_blast", label: "Не дробеструится", from: product.skip_shot_blast ? "Да" : "Нет", to: form.skip_shot_blast ? "Да" : "Нет" });
  if (!eq(form.aliases ?? [], product.aliases ?? [])) changes.push({ field: "aliases", label: "Эквиваленты", from: (product.aliases ?? []).join(", ") || "—", to: (form.aliases ?? []).join(", ") || "—" });
  if (!eq(form.lengths ?? [], product.lengths ?? [])) changes.push({ field: "lengths", label: "Длины", from: productLens.join(", ") || "—", to: formLengths.join(", ") || "—" });
  const formPrimary = primaryLength(form);
  const productPrimary = primaryLength(product);
  if (!eq(formPrimary, productPrimary)) {
    changes.push({
      field: "lengths",
      label: "Основная длина",
      from: productPrimary != null ? `${productPrimary} мм` : "—",
      to: formPrimary != null ? `${formPrimary} мм` : "—",
    });
  }
  if (!eq(form.is_laminated ?? false, product.is_laminated)) changes.push({ field: "is_laminated", label: "Ламинируется", from: product.is_laminated ? "Да" : "Нет", to: form.is_laminated ? "Да" : "Нет" });
  if (!eq(form.dimension_state ?? "length", product.dimension_state ?? "length")) changes.push({ field: "dimension_state", label: "Размерность", from: product.dimension_state ?? "length", to: form.dimension_state ?? "length" });
  if (!eq(form.third_party ?? false, product.third_party ?? false)) changes.push({ field: "third_party", label: "Сторонний заказ", from: product.third_party ? "Да" : "Нет", to: form.third_party ? "Да" : "Нет" });
  if (!eq(form.customer ?? null, product.customer ?? null)) changes.push({ field: "customer", label: "Заказчик", from: product.customer ?? "—", to: form.customer ?? "—" });
  if (!eq(form.pack ?? null, product.pack ?? null)) changes.push({ field: "pack", label: "Комплект", from: packText(product.pack), to: packText(form.pack) });
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

/** Превью расчёта листа (#126): один item kind='sheet'. */
type HangerSheetPreviewState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; result: HangerCalcResult | null }
  | { status: "error"; message: string };

/** Слоты изображения артикула (#465): фото, превью для списков, чертёж. */
type PhotoSlot = "full" | "thumb" | "drawing";

/** Состояние операции одного слота: прогресс и ошибка не общие. */
type SlotOperation = { busy: "upload" | "delete" | null; error: string | null };

const EMPTY_SLOT_OPERATION: SlotOperation = { busy: null, error: null };

function emptySlotOperations(): Record<PhotoSlot, SlotOperation> {
  return {
    full: { ...EMPTY_SLOT_OPERATION },
    thumb: { ...EMPTY_SLOT_OPERATION },
    drawing: { ...EMPTY_SLOT_OPERATION },
  };
}

/** Форматы, которые принимает любой слот (конвертация PDF — вне карточки). */
const PHOTO_SLOT_ACCEPT = "image/png,image/jpeg";
const PHOTO_SLOT_HINT = "PNG или JPEG";

const PHOTO_DELETE_TITLES: Record<PhotoSlot, string> = {
  full: "Удалить фото?",
  thumb: "Удалить превью?",
  drawing: "Удалить чертёж?",
};

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
  // undefined — слот не трогали в этой сессии, null — удалён локально:
  // так пустой слот честный, а не подставляет соседний файл (#465).
  const [localPhotoFull, setLocalPhotoFull] = useState<string | null | undefined>(undefined);
  const [localPhotoThumb, setLocalPhotoThumb] = useState<string | null | undefined>(undefined);
  const [localPhotoDrawing, setLocalPhotoDrawing] = useState<string | null | undefined>(undefined);
  const [localVisualOrigin, setLocalVisualOrigin] = useState<"own" | "alias" | null | undefined>(undefined);
  const [slotOperations, setSlotOperations] = useState<Record<PhotoSlot, SlotOperation>>(emptySlotOperations);
  const [pendingDelete, setPendingDelete] = useState<PhotoSlot | null>(null);
  const [uploadFullModal, setUploadFullModal] = useState(false);
  const [uploadThumbModal, setUploadThumbModal] = useState(false);
  const [uploadDrawingModal, setUploadDrawingModal] = useState(false);
  const [newLength, setNewLength] = useState("");
  const [form, setForm] = useState<CreateProductInput>(() => buildInitialForm(product, mode));
  const [hangerPreview, setHangerPreview] = useState<HangerPreviewState>({ status: "idle" });
  // Листы 2D/3D (#126): значения осей из секции измерений + live-превью расчёта.
  const [dimValues, setDimValues] = useState<Record<string, string>>({});
  const [sheetPreview, setSheetPreview] = useState<HangerSheetPreviewState>({ status: "idle" });
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
    setLocalPhotoFull(undefined);
    setLocalPhotoThumb(undefined);
    setLocalPhotoDrawing(undefined);
    setLocalVisualOrigin(undefined);
    setSlotOperations(emptySlotOperations());
    setPendingDelete(null);
    setNewLength("");
    setHangerPreview({ status: "idle" });
    setSheetPreview({ status: "idle" });
    setDimValues({});
    setChangesOpen(false);
  }, [product?.id, mode]);
  const formLengths = useMemo(() => productLengths(form), [form.lengths]);
  // Норма-сирота: ручное N под длиной, которой нет в реестре (ADR-0047).
  // Считаем по состоянию формы: введённая длина или снятое значение
  // снимают предупреждение сразу, ещё до сохранения.
  const orphanNormKeyList = useMemo(
    () => orphanNormKeys({
      dimension_state: form.dimension_state,
      lengths: form.lengths,
      quantity_per_hanger: form.quantity_per_hanger,
    }),
    [form.dimension_state, form.lengths, form.quantity_per_hanger],
  );
  // Явный режим подвеса (#127): единый для 1D/2D/3D, без data-driven вывода.
  const autoMode = (form.hanger_mode ?? "auto") === "auto";
  const sheetMode: HangerMode = form.hanger_mode ?? "auto";
  const isSheet = isSheetState(form.dimension_state);
  // Сторонний заказ — односторонняя отметка: «Свой» не показываем, это
  // состояние по умолчанию. Норма объёмного артикула без длины живёт под
  // ключом `default` (ADR-0075), а не под длиной полотна.
  const isThirdParty = form.third_party === true;
  const isThirdPartyVolume = isThirdParty && form.dimension_state === "volume";
  const defaultManual = form.quantity_per_hanger?.[DEFAULT_HANGER_KEY]?.manual ?? null;
  const canUseAuto = !isLengthState(form.dimension_state) || Boolean(
    typeof form.perimeter_mm === "number" && form.perimeter_mm > 0 &&
    typeof form.mount_width_mm === "number" && form.mount_width_mm > 0
  );
  const autoUnavailable = !canUseAuto;

  const handleHangerModeChange = (nextMode: HangerMode) => {
    if (nextMode === "auto" && autoUnavailable) return;
    setForm((current) => {
      if (nextMode !== "manual" || current.hanger_mode !== "auto") {
        return { ...current, hanger_mode: nextMode };
      }
      const nextManual = { ...(current.quantity_per_hanger ?? {}) };
      for (const [index, length] of productLengths(current).entries()) {
        const key = lengthKey(length);
        const autoValue = hangerPreview.status === "ready" ? hangerPreview.results?.[index]?.total : null;
        nextManual[key] = {
          auto: null,
          manual: nextManual[key]?.manual ?? (autoValue != null && autoValue > 0 ? Math.trunc(autoValue) : null),
        };
      }
      return { ...current, hanger_mode: nextMode, quantity_per_hanger: nextManual };
    });
  };

  // Длина полотна: из осей формы (create/edit) или сохранённых dimensions.
  const sheetLen = useMemo(() => {
    const parsed = Number(dimValues.length_mm);
    // Без Math.trunc: ключ словаря должен совпадать с бэкендом и для дробных
    // длин ('1000.5'), _length_key сохраняет точное значение (#126, ревью).
    if (Number.isFinite(parsed) && parsed > 0) return parsed;
    return product?.dimensions?.length_mm ?? null;
  }, [dimValues.length_mm, product?.dimensions?.length_mm]);

  useEffect(() => {
    if (!isSheet || sheetMode !== "auto") {
      setSheetPreview({ status: "idle" });
      return;
    }
    const lengthMm = sheetLen;
    const widthRaw = Number(dimValues.width_mm);
    if (!lengthMm || !Number.isFinite(widthRaw) || widthRaw <= 0) {
      setSheetPreview({ status: "idle" });
      return;
    }
    const heightRaw = form.dimension_state === "volume" ? Number(dimValues.height_mm) : NaN;
    const heightMm = Number.isFinite(heightRaw) && heightRaw > 0 ? heightRaw : null;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setSheetPreview({ status: "loading" });
      calcHanger([
        { kind: "sheet", perimeter_mm: null, mount_width_mm: null, length_mm: lengthMm, width_mm: widthRaw, height_mm: heightMm },
      ])
        .then((resp) => {
          if (!cancelled) setSheetPreview({ status: "ready", result: resp.results[0] ?? null });
        })
        .catch((e) => {
          if (!cancelled) setSheetPreview({ status: "error", message: getErrorMessage(e) });
        });
    }, 400);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [isSheet, sheetMode, sheetLen, dimValues.width_mm, dimValues.height_mm, form.dimension_state]);

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
        (form.lengths ?? []).map((length) => ({
          perimeter_mm: perimeter,
          mount_width_mm: mountWidth,
          length_mm: effectiveRawLength(length),
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
    const idx = (form.lengths ?? []).findIndex((record) => record.length_mm === length);
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

  /** Ручная норма объёмного артикула без длины — ключ `default` (ADR-0075). */
  const updateDefaultManual = (value: number | null) => {
    setForm((f) => ({
      ...f,
      quantity_per_hanger: {
        ...(f.quantity_per_hanger ?? {}),
        [DEFAULT_HANGER_KEY]: { auto: null, manual: value },
      },
    }));
  };

  /** Комплект меняет норму: 4 × 2 = 8 шт на подвес. */
  const applyPack = (pack: ThirdPartyPack) => {
    const norm = packNorm(pack);
    setForm((f) => ({
      ...f,
      pack,
      quantity_per_hanger: (f.dimension_state ?? "length") === "volume"
        ? { ...(f.quantity_per_hanger ?? {}), [DEFAULT_HANGER_KEY]: { auto: null, manual: norm } }
        : f.quantity_per_hanger,
    }));
  };

  const toggleThirdParty = (checked: boolean) => {
    setForm((f) => {
      if (!checked) {
        return { ...f, third_party: false, customer: null, pack: null };
      }
      const isVolume = (f.dimension_state ?? "length") === "volume";
      const pack = f.pack ?? { sets_per_hanger: 1, pieces_per_set: 1 };
      const norm = packNorm(pack);
      return {
        ...f,
        third_party: true,
        pack,
        // Ручная норма default допустима только в manual-режиме (ADR-0075).
        hanger_mode: isVolume ? "manual" : f.hanger_mode,
        quantity_per_hanger: isVolume
          ? { ...(f.quantity_per_hanger ?? {}), [DEFAULT_HANGER_KEY]: { auto: null, manual: norm } }
          : f.quantity_per_hanger,
      };
    });
  };

  /** Явная очистка нормы-сироты: null по ключу уходит в PATCH (ADR-0047). */
  const clearOrphanNorm = useCallback((key: string) => {
    setForm((f) => ({
      ...f,
      quantity_per_hanger: {
        ...(f.quantity_per_hanger ?? {}),
        [key]: { auto: null, manual: null },
      },
    }));
  }, []);
  const setLengths = useCallback((values: Array<number | ProductLength>) => {
    const normalized = normalizeLengths(values.map((value) => typeof value === "number" ? value : value.length_mm));
    setForm((f) => {
      const previous = new Map((f.lengths ?? []).map((length) => [length.length_mm, length]));
      const currentPrimary = f.lengths?.find((length) => length.is_primary)?.length_mm;
      const primary = currentPrimary != null && normalized.includes(currentPrimary) ? currentPrimary : normalized[0] ?? null;
      return {
        ...f,
        lengths: normalized.map((length) => {
          const old = previous.get(length);
          return { length_mm: length, raw_length_mm: old?.raw_length_mm ?? null, is_primary: length === primary };
        }),
        // Норма под снятой длиной — ручной ввод: её снятие уходит в PATCH
        // явным null, иначе сервер отклонит правку как потерю значения
        // (ADR-0047). Ключ остаётся в словаре формы — отсюда и payload.
        quantity_per_hanger: clearNormsOfRemovedLengths(
          f.quantity_per_hanger,
          productLengths(f),
          normalized,
        ),
      };
    });
  }, []);
  const commitLength = () => {
    const val = parseFloat(newLength);
    if (isNaN(val) || val <= 0) return;
    setLengths([...(form.lengths ?? []), { length_mm: val, raw_length_mm: null, is_primary: false }]);
    setNewLength("");
  };

  const buildPatch = useCallback((): PatchProductInput => {
    if (!product) return {};
    const patch: PatchProductInput = {};
    const formLengths = productLengths(form);
    const productLens = productLengths(product);
    const formPrimaryLength = primaryLength(form);
    const productPrimaryLength = primaryLength(product);
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
    if (!eq(formPrimaryLength, productPrimaryLength)) patch.lengths = form.lengths ?? [];
    if (!eq(form.weight_per_meter, product.weight_per_meter)) patch.weight_per_meter = form.weight_per_meter;
    if (!eq(form.perimeter_mm ?? null, product.perimeter_mm ?? null)) patch.perimeter_mm = form.perimeter_mm ?? null;
    if (!eq(form.mount_width_mm ?? null, product.mount_width_mm ?? null)) patch.mount_width_mm = form.mount_width_mm ?? null;
    const merged = mergedManuals(form.quantity_per_hanger ?? null, product.quantity_per_hanger ?? null);
    if (!eq(merged, manualByLength(product.quantity_per_hanger ?? null))) {
      // Лист (#126): ключ словаря — длина полотна из осей, не список длин профиля.
      // Сторонний объёмный заказ нормируется ключом `default`, а не длиной.
      const payloadLengths = isThirdPartyVolume
        ? []
        : !isSheet && formLengths.length > 0
          ? formLengths
          : sheetLen != null
            ? [sheetLen]
            : [];
      // Ключи вне реестра (норма-сирота, снятая длина) едут в payload иначе:
      // сервер не отличит их снятие от молчаливой правки карточки (ADR-0047).
      const extraKeys = Object.keys(form.quantity_per_hanger ?? {}).filter(
        (key) =>
          !payloadLengths.some((length) => lengthKey(length) === key) &&
          // `default` — только для объёмного артикула (ADR-0075).
          (key !== DEFAULT_HANGER_KEY || form.dimension_state === "volume"),
      );
      patch.quantity_per_hanger = buildManualPayloadDict(payloadLengths, merged, extraKeys);
    }
    if (!eq(form.cross_section, product.cross_section)) patch.cross_section = form.cross_section;
    if (!eq(form.skip_shot_blast, product.skip_shot_blast)) patch.skip_shot_blast = form.skip_shot_blast;
    if (!eq(form.aliases ?? [], product.aliases ?? [])) patch.aliases = form.aliases;
    if (!eq(form.lengths ?? [], product.lengths ?? [])) patch.lengths = form.lengths ?? [];
    if (!eq(primaryLength(form), primaryLength(product))) patch.lengths = form.lengths ?? [];
    if (!eq(form.is_laminated ?? false, product.is_laminated)) patch.is_laminated = form.is_laminated;
    if (!eq(form.dimension_state ?? "length", product.dimension_state ?? "length")) patch.dimension_state = form.dimension_state;
    if (!eq(form.hanger_mode ?? "auto", product.hanger_mode ?? "auto")) patch.hanger_mode = form.hanger_mode ?? "auto";
    if (!eq(form.third_party ?? false, product.third_party ?? false)) patch.third_party = form.third_party ?? false;
    if (!eq(form.customer ?? null, product.customer ?? null)) patch.customer = form.customer ?? null;
    if (!eq(form.pack ?? null, product.pack ?? null)) patch.pack = form.pack ?? null;
    return patch;
  }, [form, product, isSheet, sheetLen, isThirdPartyVolume]);

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
  // Лист (#126): в ручном режиме значение должно быть положительным.
  // У стороннего объёмного заказа норма — `default`, длины полотна может не быть.
  const sheetManual = isThirdPartyVolume
    ? defaultManual
    : sheetLen != null
      ? manualForLength(sheetLen)
      : null;
  const sheetManualInvalid = isSheet && sheetMode === "manual" && sheetManual != null && !(sheetManual > 0);
  const defaultInvalid = isThirdPartyVolume && defaultManual != null && !(defaultManual > 0);
  const packInvalid =
    isThirdParty &&
    (form.pack == null ||
      form.pack.sets_per_hanger <= 0 ||
      form.pack.pieces_per_set <= 0);
  const hasValidationErrors =
    (autoMode && autoUnavailable) ||
    perimeterInvalid ||
    mountWidthInvalid ||
    quantityInvalid ||
    sheetManualInvalid ||
    defaultInvalid ||
    packInvalid ||
    (isThirdPartyVolume && sheetMode !== "manual");

  useEffect(() => {
    onDirtyChange?.(isDirty);
    onChangesChange?.(changes);
  }, [isDirty, onDirtyChange, onChangesChange, changes]);

  const revokeBlob = (url: string | null | undefined) => {
    if (url?.startsWith("blob:")) URL.revokeObjectURL(url);
  };

  /** Заменить локальный URL одного слота, не трогая соседние (#465). */
  const replaceLocalSlot = (slot: PhotoSlot, url: string | null) => {
    if (slot === "full") {
      revokeBlob(localPhotoFull);
      setLocalPhotoFull(url);
    } else if (slot === "drawing") {
      revokeBlob(localPhotoDrawing);
      setLocalPhotoDrawing(url);
    } else {
      revokeBlob(localPhotoThumb);
      setLocalPhotoThumb(url);
    }
  };

  const updateSlotOperation = (slot: PhotoSlot, patch: Partial<SlotOperation>) => {
    setSlotOperations((current) => ({
      ...current,
      [slot]: { ...current[slot], ...patch },
    }));
  };

  // Cleanup blob URLs on unmount
  useEffect(() => {
    return () => {
      if (localPhotoFull?.startsWith("blob:")) URL.revokeObjectURL(localPhotoFull);
      if (localPhotoThumb?.startsWith("blob:")) URL.revokeObjectURL(localPhotoThumb);
      if (localPhotoDrawing?.startsWith("blob:")) URL.revokeObjectURL(localPhotoDrawing);
    };
  }, [localPhotoFull, localPhotoThumb, localPhotoDrawing]);

  const handlePhotoUpload = async (file: File, slot: PhotoSlot) => {
    if (!product?.id) return;
    updateSlotOperation(slot, { busy: "upload", error: null });
    try {
      const updated = await uploadProductPhoto(product.id, file, slot);
      // Свой файл слота: фото не подставляется вместо чертежа и наоборот.
      const stored =
        slot === "full"
          ? updated.photo_full
          : slot === "thumb"
            ? updated.photo_thumb
            : updated.drawing_full;
      replaceLocalSlot(slot, stored ? productPhotoUrl(updated, slot) : null);
      if (slot === "drawing") setLocalVisualOrigin(updated.visual_origin ?? "own");
    } catch (error) {
      // Ошибка одного слота остаётся в своём блоке и не трогает соседний.
      updateSlotOperation(slot, { error: getErrorMessage(error) });
    } finally {
      updateSlotOperation(slot, { busy: null });
    }
  };

  const handlePhotoDelete = async (slot: PhotoSlot) => {
    if (!product?.id) return;
    updateSlotOperation(slot, { busy: "delete", error: null });
    try {
      await deleteProductPhoto(product.id, slot);
      replaceLocalSlot(slot, null);
      if (slot === "drawing") setLocalVisualOrigin(null);
    } catch (error) {
      updateSlotOperation(slot, { error: getErrorMessage(error) });
    } finally {
      updateSlotOperation(slot, { busy: null });
    }
  };

  const handlePhotoSelect = (file: File, slot: PhotoSlot) => {
    if (isCreate) return;
    void handlePhotoUpload(file, slot);
  };

  // #404: версия идёт в URL каждого слота отдельно. Локальная после загрузки
  // уже содержит `?v=`, сохранённые в товаре — получают свою версию здесь.
  // Слот без своего файла пуст: подстановка соседнего — только в просмотре.
  const fullPhotoUrl =
    localPhotoFull === undefined
      ? product?.photo_full
        ? productPhotoUrl(product, "full")
        : null
      : localPhotoFull;
  const thumbPhotoUrl =
    localPhotoThumb === undefined
      ? product?.photo_thumb
        ? productPhotoUrl(product, "thumb")
        : null
      : localPhotoThumb;
  const drawingPhotoUrl =
    localPhotoDrawing === undefined
      ? product?.drawing_full
        ? productPhotoUrl(product, "drawing")
        : null
      : localPhotoDrawing;
  const visualOrigin = localVisualOrigin === undefined ? product?.visual_origin : localVisualOrigin;
  const drawingFromAlias = Boolean(drawingPhotoUrl) && visualOrigin === "alias";
  // Полный просмотр открывается чертежом, если он есть; иначе фото (ADR-0078).
  const fullscreenUrl = drawingPhotoUrl ?? fullPhotoUrl ?? thumbPhotoUrl;
  const anySlotBusy = Object.values(slotOperations).some((operation) => operation.busy !== null);

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
          {/* Два независимых слота (#465): «Фото изделия» и «Чертёж».
              У каждого своё превью, загрузка и удаление, а пустой слот
              честный — соседний файл в карточке не подставляется. */}
          <section
            aria-label="Фото изделия"
            className="rounded-lg border bg-muted/20 p-3 space-y-3"
          >
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-sm font-medium">Фото изделия</h3>
              <span className="text-[11px] text-muted-foreground">{PHOTO_SLOT_HINT}</span>
            </div>

            <div
              className={cn(
                "relative w-full h-56 bg-muted rounded-lg flex items-center justify-center overflow-hidden transition-all",
                fullPhotoUrl && "cursor-pointer hover:ring-2 ring-primary",
              )}
              onClick={() => {
                if (fullPhotoUrl) setFullscreenPhoto(fullPhotoUrl);
              }}
            >
              {fullPhotoUrl ? (
                <>
                  <img
                    src={fullPhotoUrl}
                    alt={`${product?.name || "Артикул"} — фото`}
                    className="w-full h-full object-contain pointer-events-none"
                  />
                  <div className="absolute bottom-2 right-2 p-2 bg-black/50 text-white rounded-full pointer-events-none">
                    <Maximize2 className="w-4 h-4" />
                  </div>
                </>
              ) : (
                <div className="text-center text-sm text-muted-foreground">
                  <Image className="w-10 h-10 mx-auto mb-1" />
                  Фото нет
                </div>
              )}
            </div>

            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                className="flex-1"
                disabled={slotOperations.full.busy !== null || isCreate || readOnly}
                onClick={() => setUploadFullModal(true)}
              >
                <Camera className="w-4 h-4 mr-2" />
                {slotOperations.full.busy === "upload"
                  ? "Загрузка…"
                  : fullPhotoUrl
                    ? "Заменить фото"
                    : "Загрузить фото"}
              </Button>
              <Button
                type="button"
                variant="outline"
                aria-label="Удалить фото"
                disabled={!fullPhotoUrl || slotOperations.full.busy !== null || readOnly}
                onClick={() => setPendingDelete("full")}
              >
                <Trash2 className="w-4 h-4 mr-2" />
                Удалить
              </Button>
            </div>
            {slotOperations.full.busy === "delete" && (
              <p className="text-xs text-muted-foreground">Удаление…</p>
            )}
            {slotOperations.full.error && (
              <p role="alert" className="text-xs text-destructive">
                {slotOperations.full.error}
              </p>
            )}

            <div className="flex items-center gap-3 border-t pt-3">
              <div
                className={cn(
                  "relative w-16 h-16 shrink-0 bg-muted rounded-lg flex items-center justify-center overflow-hidden transition-all",
                  thumbPhotoUrl && "cursor-pointer hover:ring-2 ring-primary",
                )}
                onClick={() => {
                  if (thumbPhotoUrl) setFullscreenPhoto(thumbPhotoUrl);
                }}
              >
                {thumbPhotoUrl ? (
                  <>
                    <img
                      src={thumbPhotoUrl}
                      alt={`${product?.name || "Артикул"} — превью`}
                      className="w-full h-full object-contain pointer-events-none"
                    />
                    <div className="absolute bottom-1 right-1 p-1 bg-black/50 text-white rounded-full pointer-events-none">
                      <Maximize2 className="w-3 h-3" />
                    </div>
                  </>
                ) : (
                  <span className="text-[10px] text-muted-foreground text-center px-1">
                    Превью нет
                  </span>
                )}
              </div>

              <div className="flex-1 min-w-0 space-y-1">
                <p className="text-xs text-muted-foreground">Превью для списков</p>
                <div className="flex gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    className="flex-1"
                    disabled={slotOperations.thumb.busy !== null || isCreate || readOnly}
                    onClick={() => setUploadThumbModal(true)}
                  >
                    <Camera className="w-4 h-4 mr-2" />
                    {slotOperations.thumb.busy === "upload"
                      ? "Загрузка…"
                      : thumbPhotoUrl
                        ? "Заменить превью"
                        : "Загрузить превью"}
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    aria-label="Удалить превью"
                    disabled={!thumbPhotoUrl || slotOperations.thumb.busy !== null || readOnly}
                    onClick={() => setPendingDelete("thumb")}
                  >
                    <Trash2 className="w-4 h-4" />
                  </Button>
                </div>
                {slotOperations.thumb.error && (
                  <p role="alert" className="text-xs text-destructive">
                    {slotOperations.thumb.error}
                  </p>
                )}
              </div>
            </div>
          </section>

          <section
            aria-label="Чертёж"
            className="rounded-lg border bg-muted/20 p-3 space-y-3"
          >
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-sm font-medium">Чертёж</h3>
              <div className="flex items-center gap-2">
                {drawingFromAlias && (
                  <Badge variant="outline" className="text-[10px]">
                    Чертёж алиаса
                  </Badge>
                )}
                <span className="text-[11px] text-muted-foreground">{PHOTO_SLOT_HINT}</span>
              </div>
            </div>

            <div
              className={cn(
                "relative w-full h-56 bg-muted rounded-lg flex items-center justify-center overflow-hidden transition-all",
                drawingPhotoUrl && "cursor-pointer hover:ring-2 ring-primary",
              )}
              onClick={() => {
                if (drawingPhotoUrl) setFullscreenPhoto(drawingPhotoUrl);
              }}
            >
              {drawingPhotoUrl ? (
                <>
                  <img
                    src={drawingPhotoUrl}
                    alt={`${product?.name || "Артикул"} — чертёж`}
                    className="w-full h-full object-contain pointer-events-none"
                  />
                  <div className="absolute bottom-2 right-2 p-2 bg-black/50 text-white rounded-full pointer-events-none">
                    <Maximize2 className="w-4 h-4" />
                  </div>
                </>
              ) : (
                <div className="text-center text-sm text-muted-foreground">
                  <Image className="w-10 h-10 mx-auto mb-1" />
                  Чертежа нет
                </div>
              )}
            </div>

            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                className="flex-1"
                disabled={slotOperations.drawing.busy !== null || isCreate || readOnly}
                onClick={() => setUploadDrawingModal(true)}
              >
                <Camera className="w-4 h-4 mr-2" />
                {slotOperations.drawing.busy === "upload"
                  ? "Загрузка…"
                  : drawingPhotoUrl
                    ? "Заменить чертёж"
                    : "Загрузить чертёж"}
              </Button>
              <Button
                type="button"
                variant="outline"
                aria-label="Удалить чертёж"
                disabled={!drawingPhotoUrl || slotOperations.drawing.busy !== null || readOnly}
                onClick={() => setPendingDelete("drawing")}
              >
                <Trash2 className="w-4 h-4 mr-2" />
                Удалить
              </Button>
            </div>
            {slotOperations.drawing.busy === "delete" && (
              <p className="text-xs text-muted-foreground">Удаление…</p>
            )}
            {slotOperations.drawing.error && (
              <p role="alert" className="text-xs text-destructive">
                {slotOperations.drawing.error}
              </p>
            )}
          </section>

          <Button
            type="button"
            variant="outline"
            className="w-full"
            disabled={!fullscreenUrl}
            onClick={() => {
              if (fullscreenUrl) setFullscreenPhoto(fullscreenUrl);
            }}
          >
            <Maximize2 className="w-4 h-4 mr-2" />
            Открыть полностью
          </Button>

          {isCreate && (
            <p className="text-xs text-muted-foreground text-center">
              Фото и чертёж загружаются после создания товара
            </p>
          )}
        </div>

        <div className="space-y-3">
          {/* Сторонний заказ (T-383): отметка односторонняя — «Свой» не
              показываем, это состояние по умолчанию. Поля заказчика и
              комплекта живут рядом, норма считается из комплекта. */}
          <label
            className={cn(
              "flex items-start gap-2 rounded-lg border px-3 py-2 cursor-pointer transition-colors",
              isThirdParty
                ? "border-amber-300 bg-amber-50"
                : "border-border bg-muted/20 hover:bg-muted/40",
              readOnly && "cursor-default",
            )}
          >
            <Checkbox
              id="third_party"
              className="mt-0.5"
              checked={isThirdParty}
              onCheckedChange={(checked) => toggleThirdParty(checked === true)}
              disabled={readOnly}
            />
            <span className="min-w-0">
              <span className={cn("block text-sm font-medium", isThirdParty && "text-amber-900")}>
                Сторонний
              </span>
              <span className="block text-xs text-muted-foreground">
                материал заказчика — завод только обрабатывает. Обычный артикул — состояние по умолчанию.
              </span>
            </span>
          </label>

          {isThirdParty && (
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 rounded-lg border border-amber-200 bg-amber-50/60 p-3">
              <div className="space-y-1">
                <label className="text-xs font-medium text-amber-900" htmlFor="third-party-customer">
                  Заказчик
                </label>
                <Input
                  id="third-party-customer"
                  value={form.customer ?? ""}
                  onChange={(e) => update("customer", e.target.value || null)}
                  placeholder="ГорКомплекс"
                  disabled={readOnly}
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium text-amber-900" htmlFor="third-party-sets">
                  Комплектов на подвес
                </label>
                <Input
                  id="third-party-sets"
                  type="number"
                  min={1}
                  className="h-9"
                  value={form.pack?.sets_per_hanger || ""}
                  onChange={(e) =>
                    applyPack({
                      sets_per_hanger: parseNumericInput(e.target.value) ?? 0,
                      pieces_per_set: form.pack?.pieces_per_set ?? 0,
                    })
                  }
                  disabled={readOnly}
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium text-amber-900" htmlFor="third-party-pieces">
                  Предметов в комплекте
                </label>
                <Input
                  id="third-party-pieces"
                  type="number"
                  min={1}
                  className="h-9"
                  value={form.pack?.pieces_per_set || ""}
                  onChange={(e) =>
                    applyPack({
                      sets_per_hanger: form.pack?.sets_per_hanger ?? 0,
                      pieces_per_set: parseNumericInput(e.target.value) ?? 0,
                    })
                  }
                  disabled={readOnly}
                />
              </div>
              <p className="sm:col-span-3 text-xs text-amber-800">
                {packNorm(form.pack) != null
                  ? `Норма: ${packNorm(form.pack)} шт на подвес (${packText(form.pack)})`
                  : "Укажите комплекты и предметы — норма посчитается сама."}
              </p>
              {packInvalid && (
                <p className="sm:col-span-3 text-xs text-destructive">
                  Комплектов и предметов должно быть больше нуля.
                </p>
              )}
            </div>
          )}

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
              {/* Флаг выведенный (ADR-0023, #146): есть пары в секции «Пары» ниже. */}
              <div className="flex items-center gap-2 h-5">
                <span className="text-sm font-medium leading-none">Парный профиль:</span>
                <span
                  className={cn(
                    "text-xs px-1.5 py-0.5 rounded-sm",
                    (product?.is_paired_profile ?? false)
                      ? "bg-purple-100 text-purple-800 font-medium"
                      : "bg-muted text-muted-foreground",
                  )}
                >
                  {product?.is_paired_profile ? "Да" : isCreate ? "— нет" : "Нет"}
                </span>
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
                  onValuesChange={setDimValues}
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
                        // Enter при наборе через IME закрывает композицию.
                        if (e.nativeEvent.isComposing || e.keyCode === 229) return;
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
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">Режим подвеса:</span>
                  <RadioGroup
                    value={autoMode ? "auto" : "manual"}
                    onValueChange={(val) => handleHangerModeChange(val as HangerMode)}
                    disabled={readOnly}
                    className="flex items-center gap-4"
                  >
                    <div className="flex items-center gap-1.5">
                      <RadioGroupItem value="auto" id="hanger-mode-auto" disabled={autoUnavailable} />
                      <label htmlFor="hanger-mode-auto" className={cn("text-sm cursor-pointer", autoUnavailable && "text-muted-foreground/60 cursor-not-allowed", autoMode && "font-semibold")}>Авто</label>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <RadioGroupItem value="manual" id="hanger-mode-manual" />
                      <label htmlFor="hanger-mode-manual" className={cn("text-sm cursor-pointer", !autoMode && "font-semibold")}>Вручную</label>
                    </div>
                  </RadioGroup>
                </div>
                <div className="flex items-start gap-4">
                  <div className="rounded-md border bg-background overflow-hidden inline-block min-w-0 shrink-0">
                    <table className="text-sm">
                      <thead>
                        <tr className="bg-muted/50 text-xs text-muted-foreground border-b">
                          <th className="text-left font-medium px-3 py-2">
                            Основная
                          </th>
                          <th className="text-left font-medium px-3 py-2">Кол-во на подвесе, шт</th>
                          <th className="text-left font-medium px-2 py-2 w-[100px] min-w-[100px] max-w-[100px]">Нормальная, мм</th>
                          <th className="text-left font-medium px-2 py-2 w-[100px] min-w-[100px] max-w-[100px]">Сырьевая длина, мм</th>
                          {!readOnly && <th className="px-2 py-2" aria-label="Действия" />}
                        </tr>
                      </thead>
                      {/* asChild вместо div-обёртки: div внутри tbody ломает раскладку таблицы,
                          строки разъезжаются с шапкой; table-row-group перекрывает grid из обёртки */}
                      <RadioGroup
                        asChild
                        className="table-row-group"
                        value={primaryLength(form) != null ? String(primaryLength(form)) : undefined}
                        onValueChange={(val) => {
                          const primary = Number(val);
                          setForm((f) => ({ ...f, lengths: (f.lengths ?? []).map((length) => ({ ...length, is_primary: length.length_mm === primary })) }));
                        }}
                        disabled={readOnly}
                      >
                        <tbody>
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
                                      <Link
                                        to="/references/raw-materials?view=calc"
                                        className="text-xs font-medium text-emerald-700 underline decoration-emerald-400 underline-offset-2 whitespace-nowrap hover:text-emerald-800"
                                        onClick={(event) => {
                                          event.stopPropagation();
                                          onCancel();
                                        }}
                                      >
                                        авто
                                      </Link>
                                    )}
                                  </div>
                                </td>
                                <td className="px-2 py-1.5 w-[100px] min-w-[100px] max-w-[100px] text-center">
                                  <label htmlFor={`primary-${len}`} className={cn("cursor-pointer", primaryLength(form) === len && "font-semibold")}>{len}</label>
                                </td>
                                <td className="px-2 py-1.5 w-[100px] min-w-[100px] max-w-[100px]">
                                  <Input
                                    type="number"
                                    className="h-9 w-full"
                                    value={(form.lengths ?? []).find((length) => length.length_mm === len)?.raw_length_mm ?? len}
                                    onChange={(e) => {
                                      const parsed = parseNumericInput(e.target.value);
                                      setForm((f) => ({ ...f, lengths: (f.lengths ?? []).map((length) => length.length_mm === len ? { ...length, raw_length_mm: parsed } : length) }));
                                    }}
                                    disabled={readOnly}
                                    aria-label={`Сырьевая длина для ${len} мм`}
                                  />
                                </td>
                                {!readOnly && (
                                  <td className="px-2 py-1.5 text-right">
                                    <button
                                      type="button"
                                      onClick={() => {
                                        const vals = (form.lengths ?? []).filter((_, i) => i !== idx);
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
                          </tbody>
                        </RadioGroup>
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
                    {formLengths.length > 0 && ` Основная длина ${primaryLength(form) ?? formLengths[0]} мм → ${autoQuantityFor(primaryLength(form) ?? formLengths[0]) ?? "—"} шт.`}
                  </p>
                ) : autoMode ? (
                  <p className="text-xs text-muted-foreground">
                    Значения рассчитаны из периметра и габарита.
                  </p>
                ) : null}
                {orphanNormKeyList.length > 0 && (
                  <div
                    role="alert"
                    className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 space-y-1"
                  >
                    <p className="text-xs text-amber-900">
                      Норма подвеса не применима ни к одной длине: карточка не сохранится,
                      пока значение не удалено или в реестр не введена совпадающая длина.
                    </p>
                    {orphanNormKeyList.map((key) => (
                      <div key={key} className="flex items-center gap-2 text-xs text-amber-900">
                        <span>
                          {key} мм — {form.quantity_per_hanger?.[key]?.manual ?? "—"} шт
                        </span>
                        {!readOnly && (
                          <button
                            type="button"
                            onClick={() => clearOrphanNorm(key)}
                            className="underline underline-offset-2 hover:text-amber-950"
                          >
                            Удалить норму
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                {quantityInvalid && (
                  <p className="text-xs text-destructive">Значение должно быть больше 0</p>
                )}
              </>
            ) : (
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">Режим подвеса:</span>
                  <RadioGroup
                    value={sheetMode}
                    onValueChange={(val) => update("hanger_mode", val as HangerMode)}
                    disabled={readOnly}
                    className="flex items-center gap-4"
                  >
                    <div className="flex items-center gap-1.5">
                      <RadioGroupItem value="auto" id="hanger-mode-auto" disabled={isThirdPartyVolume} />
                      <label
                        htmlFor="hanger-mode-auto"
                        className={cn(
                          "text-sm cursor-pointer",
                          sheetMode === "auto" && "font-semibold",
                          isThirdPartyVolume && "text-muted-foreground/60 cursor-not-allowed",
                        )}
                      >
                        Авто
                      </label>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <RadioGroupItem value="manual" id="hanger-mode-manual" />
                      <label htmlFor="hanger-mode-manual" className={cn("text-sm cursor-pointer", sheetMode === "manual" && "font-semibold")}>Вручную</label>
                    </div>
                  </RadioGroup>
                </div>
                {isThirdPartyVolume && (
                  <p className="text-xs text-muted-foreground">
                    Для стороннего заказа норма задаётся вручную — из комплекта или числом.
                  </p>
                )}

                {sheetMode === "auto" ? (
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm">Кол-во на подвесе:</span>
                    {sheetPreview.status === "loading" ? (
                      <span className="text-sm text-muted-foreground">Расчёт…</span>
                    ) : sheetPreview.status === "ready" && sheetPreview.result ? (
                      sheetPreview.result.is_calculable ? (
                        <>
                          <span className="text-sm font-medium">{sheetPreview.result.total} шт</span>
                          <span className="rounded-sm bg-emerald-100 px-1 text-[10px] font-semibold text-emerald-800">авто</span>
                        </>
                      ) : (
                        <span className="text-xs text-destructive">{sheetPreview.result.reason ?? "Расчёт невозможен"}</span>
                      )
                    ) : sheetPreview.status === "error" ? (
                      <span className="text-xs text-destructive">{sheetPreview.message}</span>
                    ) : (
                      <span className="text-sm text-muted-foreground">— заполните длину и ширину полотна в измерениях</span>
                    )}
                  </div>
                ) : (
                  <div className="flex flex-wrap items-center gap-2">
                    <label htmlFor="sheet-manual-qty" className="text-sm">Кол-во на подвесе:</label>
                    <Input
                      id="sheet-manual-qty"
                      type="number"
                      className={cn(
                        "h-9 w-28",
                        sheetManualInvalid && "border-destructive focus-visible:ring-destructive",
                        !sheetManualInvalid && "bg-amber-50 border-amber-300",
                      )}
                      value={sheetManual ?? ""}
                      onChange={(e) => {
                        const parsed = parseNumericInput(e.target.value);
                        const value = parsed == null ? null : Math.trunc(parsed);
                        if (isThirdPartyVolume) {
                          updateDefaultManual(value);
                        } else if (sheetLen != null) {
                          updateManualForLength(sheetLen, value);
                        }
                      }}
                      disabled={readOnly || (isCreate && !isThirdPartyVolume) || (!isThirdPartyVolume && sheetLen == null)}
                    />
                    {isCreate && !isThirdPartyVolume && (
                      <span className="text-xs text-muted-foreground">
                        Ручное значение вводится после создания артикула и заведения измерений.
                      </span>
                    )}
                    {!isCreate && !isThirdPartyVolume && sheetLen == null && (
                      <span className="text-xs text-muted-foreground">Сначала укажите длину полотна в измерениях выше.</span>
                    )}
                    {sheetManualInvalid && (
                      <span className="text-xs text-destructive">Значение должно быть больше 0</span>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>

          {!isCreate && product?.id != null && (
            <ProductPairsSection productId={product.id} sku={product.sku} readOnly={readOnly} />
          )}
          {isCreate && (
            <p className="text-xs text-muted-foreground">
              Пары добавляются после создания артикула — в секции «Пары».
            </p>
          )}

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
            <Button type="submit" disabled={anySlotBusy || hasValidationErrors}>{isCreate ? "Создать" : "Сохранить"}</Button>
          )}
        </div>
      </div>

      <AlertDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {pendingDelete ? PHOTO_DELETE_TITLES[pendingDelete] : "Удалить изображение?"}
            </AlertDialogTitle>
            <AlertDialogDescription>
              Файл будет удалён из хранилища, слот останется пустым. Соседний слот
              не изменится.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel type="button">Отмена</AlertDialogCancel>
            <AlertDialogAction
              type="button"
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                if (pendingDelete) void handlePhotoDelete(pendingDelete);
              }}
            >
              Удалить
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <ImageUploadModal
        open={uploadFullModal}
        onOpenChange={setUploadFullModal}
        onFileSelected={(file) => handlePhotoSelect(file, "full")}
        title="Фото изделия"
        accept={PHOTO_SLOT_ACCEPT}
        hint={PHOTO_SLOT_HINT}
      />
      <ImageUploadModal
        open={uploadThumbModal}
        onOpenChange={setUploadThumbModal}
        onFileSelected={(file) => handlePhotoSelect(file, "thumb")}
        title="Превью для списков"
        accept={PHOTO_SLOT_ACCEPT}
        hint={PHOTO_SLOT_HINT}
      />
      <ImageUploadModal
        open={uploadDrawingModal}
        onOpenChange={setUploadDrawingModal}
        onFileSelected={(file) => handlePhotoSelect(file, "drawing")}
        title="Чертёж"
        accept={PHOTO_SLOT_ACCEPT}
        hint={PHOTO_SLOT_HINT}
      />
    </form>
  );
});
