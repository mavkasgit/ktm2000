/**
 * URL фото артикула (#404).
 *
 * `version` — версия конкретного файла с бэкенда (`photo_*_version`). Она
 * уходит в `?v=`, чтобы замена файла давала новый URL и браузерный/nginx-кэш
 * не показывал старую картинку. Пока файл не менялся, версия стабильна и URL
 * не меняется — остальные фото остаются в долгом кэше.
 *
 * Внешние URL (`http...`) не версионируются бэкендом: `photo_file_version`
 * считает версию только по файлу storage. Если вызывающий всё же передал
 * `version` явно, она добавляется и к внешнему URL — это единственный честный
 * способ не притворяться, что remote-файл под нашим контролем.
 */
export function getPhotoUrl(path: string | null, version?: string | null): string | null {
  if (!path) return null;
  const normalized = path.startsWith("http") ? path : path.replace(/\\/g, "/");
  const base = path.startsWith("http") || normalized.startsWith("/")
    ? normalized
    : `/static/${normalized}`;
  if (!version) return base;
  const separator = base.includes("?") ? "&" : "?";
  return `${base}${separator}v=${encodeURIComponent(version)}`;
}

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
