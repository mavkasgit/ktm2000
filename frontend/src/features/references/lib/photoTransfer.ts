/**
 * Перенос фото артикула из каталога: скачать файл и скопировать картинку
 * в буфер обмена.
 *
 * Копирование идёт двумя путями. В secure context (`https` или `localhost`)
 * работает `navigator.clipboard.write` с PNG-блобом. Прод открыт по HTTP на
 * LAN-IP — там Clipboard API нет, поэтому остаётся `document.execCommand("copy")`
 * по выделенной картинке: это тот же путь, которым ходит браузерное
 * «Копировать изображение» из контекстного меню.
 */

import { saveBlobAsFile } from "@/shared/lib/downloadFile";

const MIME_EXTENSIONS: Record<string, string> = {
  "image/png": "png",
  "image/jpeg": "jpg",
  "image/webp": "webp",
  "image/gif": "gif",
  "image/bmp": "bmp",
};

/** Имя файла из URL фото: `/static/products/035_206_full.png?v=…` → `035_206_full.png`. */
export function photoFileName(src: string): string {
  const path = src.split("?")[0].split("#")[0];
  const name = decodeURIComponent(path.split("/").pop() ?? "");
  // `blob:`-адрес заканчивается UUID — именем файла он быть не может.
  if (!name || src.startsWith("blob:") || !name.includes(".")) return "photo";
  return name;
}

function fileNameFor(src: string, blob: Blob): string {
  const name = photoFileName(src);
  if (name !== "photo") return name;
  return `photo.${MIME_EXTENSIONS[blob.type] ?? "png"}`;
}

async function fetchPhotoBlob(src: string): Promise<Blob> {
  const response = await fetch(src);
  if (!response.ok) {
    throw new Error(`Не удалось получить фото: ${response.status}`);
  }
  return response.blob();
}

/** Скачать фото под его именем (или `photo.<ext>` для blob-адреса). */
export async function downloadPhoto(src: string): Promise<string> {
  const blob = await fetchPhotoBlob(src);
  const fileName = fileNameFor(src, blob);
  saveBlobAsFile(blob, fileName);
  return fileName;
}

async function toPng(blob: Blob): Promise<Blob> {
  if (blob.type === "image/png") return blob;
  const bitmap = await createImageBitmap(blob);
  try {
    const canvas = document.createElement("canvas");
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("Не удалось подготовить изображение");
    context.drawImage(bitmap, 0, 0);
    return await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob((png) => (png ? resolve(png) : reject(new Error("Не удалось подготовить изображение"))), "image/png");
    });
  } finally {
    bitmap.close();
  }
}

function clipboardSupports(type: string): boolean {
  if (typeof ClipboardItem !== "undefined" && typeof ClipboardItem.supports === "function") {
    return ClipboardItem.supports(type);
  }
  // Без `ClipboardItem.supports` браузеры (Chromium) принимают только PNG.
  return type === "image/png";
}

async function copyViaClipboardApi(blob: Blob): Promise<boolean> {
  if (typeof ClipboardItem === "undefined" || !navigator.clipboard?.write) return false;
  try {
    const clipboardBlob = clipboardSupports(blob.type) ? blob : await toPng(blob);
    await navigator.clipboard.write([new ClipboardItem({ [clipboardBlob.type]: clipboardBlob })]);
    return true;
  } catch {
    return false;
  }
}

/**
 * Запасной путь для HTTP: выделить картинку и отдать `execCommand("copy")`.
 * В полноэкранном контейнере стоит `user-select: none`, поэтому на время
 * выделения оно снимается с самой картинки; если элемента под рукой нет,
 * картинка грузится во временный узел.
 */
async function copyViaSelection(src: string, image?: HTMLImageElement | null): Promise<boolean> {
  let target: HTMLImageElement;
  let holder: HTMLDivElement | null = null;

  if (image?.isConnected) {
    target = image;
  } else {
    holder = document.createElement("div");
    holder.setAttribute("aria-hidden", "true");
    holder.style.cssText = "position:fixed;left:-10000px;top:0;user-select:text;";
    target = document.createElement("img");
    target.src = src;
    holder.appendChild(target);
    document.body.appendChild(holder);
    if (typeof target.decode === "function") {
      await target.decode().catch(() => {});
    }
  }

  const previousUserSelect = target.style.userSelect;
  target.style.userSelect = "text";
  try {
    const selection = window.getSelection();
    if (!selection) return false;
    const range = document.createRange();
    range.selectNode(target);
    selection.removeAllRanges();
    selection.addRange(range);
    try {
      return document.execCommand("copy");
    } finally {
      selection.removeAllRanges();
    }
  } catch {
    return false;
  } finally {
    target.style.userSelect = previousUserSelect;
    holder?.remove();
  }
}

/**
 * Скопировать фото в буфер обмена. Бросает исключение, если браузер не дал
 * ни один из путей, — вызывающий показывает пользователю причину.
 *
 * `image` — уже показанная картинка: по ней работает запасной путь через
 * выделение, и она точно отрисована внутри полноэкранного контейнера.
 */
export async function copyPhoto(src: string, image?: HTMLImageElement | null): Promise<void> {
  const blob = await fetchPhotoBlob(src);
  if (await copyViaClipboardApi(blob)) return;
  if (await copyViaSelection(src, image)) return;
  throw new Error("Браузер не разрешил скопировать изображение");
}
