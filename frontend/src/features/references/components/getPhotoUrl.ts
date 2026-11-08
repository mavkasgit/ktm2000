/**
 * URL файла фото артикула (#404).
 *
 * `version` — версия конкретного файла с бэкенда (`photo_*_version`). Она
 * уходит в `?v=`, чтобы замена файла давала новый URL и браузерный/nginx-кэш
 * не показывал старую картинку. Пока файл не менялся, версия стабильна и URL
 * не меняется — остальные фото остаются в долгом кэше.
 *
 * Внешний URL (`http...`) возвращается как есть и не версионируется: файл не
 * в нашем storage, версию для него посчитать нечем. `?v=` к нему не
 * добавляется, даже если передан `version`.
 */
export function getPhotoUrl(path: string | null, version?: string | null): string | null {
  if (!path) return null;
  if (path.startsWith("http")) return path;

  const normalized = path.replace(/\\/g, "/");
  const base = normalized.startsWith("/") ? normalized : `/static/${normalized}`;
  if (!version) return base;
  const separator = base.includes("?") ? "&" : "?";
  return `${base}${separator}v=${encodeURIComponent(version)}`;
}
