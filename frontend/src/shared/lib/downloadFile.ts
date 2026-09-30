/**
 * Сохранение blob-ответа API как файла — единственная точка, где ответ
 * превращается в скачанный документ.
 *
 * Отдельная функция, а не копия в каждом экране: `POST`-овый клиент не
 * годится (нужен `blob`-responseType), а голая ссылка `<a href>` уводит
 * браузер в навигацию без заголовка `Authorization` — файл не приходит,
 * пользователь видит JSON `401` (ADR-0052 п.9).
 */

/** Отдать blob пользователю под именем `filename`. */
export function saveBlobAsFile(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}