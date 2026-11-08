import { getPhotoUrl } from "./getPhotoUrl";

type PhotoFields = {
  photo_thumb: string | null;
  photo_thumb_version: string | null;
  photo_full: string | null;
  photo_full_version: string | null;
};

/**
 * URL фото товара нужного вида: основной (`full`) или превью (`thumb`).
 *
 * Сначала берётся запрошенный файл, затем — парный: `full` без своего файла
 * показывает превью-заглушку и наоборот. Версия выбирается вместе с путём,
 * иначе `?v=` от одного файла попал бы в URL другого.
 */
export function productPhotoUrl(
  product: PhotoFields | null | undefined,
  kind: "thumb" | "full",
): string | null {
  if (!product) return null;

  const primary = kind === "thumb"
    ? ([product.photo_thumb, product.photo_thumb_version] as const)
    : ([product.photo_full, product.photo_full_version] as const);
  const fallback = kind === "thumb"
    ? ([product.photo_full, product.photo_full_version] as const)
    : ([product.photo_thumb, product.photo_thumb_version] as const);

  return getPhotoUrl(primary[0], primary[1]) ?? getPhotoUrl(fallback[0], fallback[1]);
}
