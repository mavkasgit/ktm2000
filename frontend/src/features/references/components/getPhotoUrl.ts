export function getPhotoUrl(path: string | null): string | null {
  if (!path) return null;
  if (path.startsWith("http")) return path;
  const normalized = path.replace(/\\/g, "/");
  return normalized.startsWith("/") ? normalized : `/static/${normalized}`;
}
