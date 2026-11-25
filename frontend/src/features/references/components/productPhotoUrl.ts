import { getPhotoUrl } from "./getPhotoUrl";

type PhotoFields = {
  photo_thumb: string | null;
  photo_thumb_version: string | null;
  photo_full: string | null;
  photo_full_version: string | null;
  /** Чертёж (#463): необязателен, чтобы старые фикстуры оставались валидными. */
  drawing_full?: string | null;
  drawing_full_version?: string | null;
};

export type ProductPhotoKind = "thumb" | "full" | "drawing";

/**
 * URL изображения товара нужного вида: основное (`full`), превью (`thumb`)
 * или чертёж (`drawing`).
 *
 * Сначала берётся запрошенный файл, затем — запасной: `full` без своего файла
 * показывает превью-заглушку, `drawing` без чертежа показывает фото/плакат
 * (ADR-0078: плакат занимает слот, пока чертежа нет). Версия выбирается вместе
 * с путём, иначе `?v=` от одного файла попал бы в URL другого.
 */
export function productPhotoUrl(
  product: PhotoFields | null | undefined,
  kind: ProductPhotoKind,
): string | null {
  if (!product) return null;

  const sources = {
    thumb: [product.photo_thumb, product.photo_thumb_version] as const,
    full: [product.photo_full, product.photo_full_version] as const,
    drawing: [product.drawing_full ?? null, product.drawing_full_version ?? null] as const,
  };
  const order = {
    thumb: [sources.thumb, sources.full],
    full: [sources.full, sources.thumb],
    drawing: [sources.drawing, sources.full, sources.thumb],
  }[kind];

  for (const [path, version] of order) {
    const url = getPhotoUrl(path, version);
    if (url) return url;
  }
  return null;
}
