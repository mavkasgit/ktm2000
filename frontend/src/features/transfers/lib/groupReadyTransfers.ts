import type { ReadyToTransferTask } from "@/shared/api/transfers";
import { formatDimensionsLabel } from "@/shared/api/stock";
import { clusterByArticle } from "@/shared/lib/clusterByArticle";

/**
 * Единица передачи — пара «задание × размер», но оператору удобнее отправить одним
 * действием строки, неразличимые для передачи: тот же артикул, того же размера,
 * с того же участка, в тот же адрес и та же операция. Такие строки собираются в
 * одну (свёрнутую по умолчанию) группу.
 *
 * Свёрнутая группа показывает СВОДНЫЕ значения (общий этап, сумма
 * `transferable_quantity`), поэтому порядок групп — порядок первого появления
 * строки — не выражает сортировку ни по одной из этих колонок. Поэтому
 * страница применяет группировку только когда сортировка не выбрана, а при
 * выбранной колонке рисует строки заданий как есть (см. `TransfersPage`).
 *
 * Порядок по умолчанию — по количеству, но с оглядкой на артикул: блоки одного
 * артикула идут подряд, а сами артикулы — по сумме «к передаче» (см.
 * `clusterBlocksBySku`). Порядок «просто по количеству» ставил один и тот же
 * артикул в два места списка, и оператор читал знакомые строки вразброс.
 *
 * Операция — часть ключа, а не только сводка: на одном артикуле, размере и
 * адресате стоят разные работы («Окно» и «Гребенка»), и общий «Передать» на них
 * отправлял бы одним действием то, что оператор считает разным.
 *
 * Участок и адресат обязательны в ключе. Страница грузит ready по ГХП, то есть
 * сразу по нескольким участкам; а ГП и П/ф — разные динамические маршруты
 * (`output_kind` в имени маршрута, см. `seeds/selection_rules.py`), поэтому по
 * `route_stage_id` они разошлись бы уже на первом участке. Ключ по участку и
 * адресату даёт то, что нужно производству: до анода ГП и П/ф идут в один адрес
 * и образуют одну строку, на аноде адресаты расходятся — строк становится две.
 */
export type ReadyTransferGroupCommon = {
  /** Подпись размера, общая для группы; `null` — строки группы не совпали (в UI «—»). */
  dimensionsLabel: string | null;
  sectionName: string | null;
  operationName: string | null;
  nextOperationName: string | null;
  nextSectionName: string | null;
};

export type ReadyTransferGroup = {
  kind: "group";
  key: string;
  productSku: string | null;
  sectionId: number;
  nextSectionId: number | null;
  /** Строки группы в порядке прихода с бэка. */
  rows: ReadyToTransferTask[];
  /** Сумма `transferable_quantity` по строкам группы. */
  totalTransferable: number;
  /** Сумма `planned_quantity` по строкам группы. */
  totalPlanned: number;
  /** Сумма `already_transferred_quantity` по строкам группы. */
  totalAlreadyTransferred: number;
  /** Все строки группы — финальный выпуск («Отправить» вместо «Передать»). */
  allFinal: boolean;
  hasNextStep: boolean;
  common: ReadyTransferGroupCommon;
};

export type ReadyTransferSingle = {
  kind: "single";
  row: ReadyToTransferTask;
};

export type ReadyTransferRowItem = ReadyTransferGroup | ReadyTransferSingle;

/** Группа хранения и производства, к которой относится участок готовой строки. */
export type ReadyTransferSpg = {
  /** Стабильный ключ блока — он же React-ключ шапки ГХП. */
  key: string;
  /** Название ГХП для шапки блока. */
  name: string;
  /** Порядок блока в списке — порядок ГХП в справочнике. */
  sortOrder: number;
  /** Цвет ГХП из справочника (`icon_color`); `null` — цвета нет. */
  color: string | null;
};

/** Блок списка «Готово к передаче»: ГХП и разложенные по нему строки. */
export type ReadyTransferSpgSection = {
  spg: ReadyTransferSpg;
  items: ReadyTransferRowItem[];
};

/** Участок без ГХП: такие строки идут отдельным блоком в конце списка. */
const UNKNOWN_SPG: ReadyTransferSpg = {
  key: "spg:none",
  name: "Без ГХП",
  sortOrder: Number.POSITIVE_INFINITY,
  color: null,
};

/**
 * Пункт этапа — участок и операция одной строкой: «Пила · Окно».
 *
 * Оператору нужен физический адрес: откуда забрать материал и куда его нести,
 * поэтому участок первичен, а операция — уточнение. Коды (`FINISHED_STOCK`) и
 * номера этапов маршрута в таблицу не попадают: это идентификаторы, а не адрес.
 *
 * Операция не повторяет участок: «Хранение: Склад готовой продукции» уже
 * содержит пункт назначения и печатается одна; совпадающие названия тоже не
 * удваиваются. У складских этапов операций нет — остаётся название участка.
 */
export function stagePointLabel(sectionName: string | null, operationName: string | null): string {
  const section = sectionName?.trim() || "";
  const operation = operationName?.trim() || "";
  if (!section && !operation) return "—";
  if (!section) return operation;
  if (!operation || operation === section) return section;
  if (operation.toLowerCase().includes(section.toLowerCase())) return operation;
  return `${section} · ${operation}`;
}

/** Строка в ready-списке = финальный выпуск, а не передача на следующий этап. */
export function isFinalReadyRow(task: ReadyToTransferTask): boolean {
  return task.is_final === true || !task.has_next_step;
}

/** Канонический вид размеров для ключа: ключи по алфавиту, `null` — отдельное состояние. */
export function dimensionsKey(dimensions: ReadyToTransferTask["dimensions"]): string {
  if (dimensions == null) return "null";
  const keys = Object.keys(dimensions).sort();
  if (keys.length === 0) return "null";
  return keys.map((key) => `${key}=${dimensions[key]}`).join(",");
}

/**
 * Идентичность строки ready-таблицы: единица передачи — пара «задание × размер».
 *
 * Один `task_id` у трансформирующей задачи (#91) даёт столько строк, сколько
 * выходов спецификации, поэтому `task_id` как ключ React не уникален. На этом
 * готовом ключе строились дубли `<tr>` — React переиспользовал узлы строк с
 * одинаковым ключом, и в DOM оказывалось больше строк, чем отдал сервер.
 *
 * Владелец выражения — здесь, рядом с `dimensionsKey`: его используют и
 * `data-row-key`, и React-ключ, и они не должны разойтись при правке одного.
 */
export function readyRowIdentity(task: ReadyToTransferTask): string {
  return `${task.task_id}:${dimensionsKey(task.dimensions)}`;
}

/** Ключ идентичности строки ready — см. комментарий к модулю. */
export function readyTransferGroupKey(task: ReadyToTransferTask): string {
  return [
    task.product_sku ?? "",
    task.section_id,
    dimensionsKey(task.dimensions),
    task.next_section_id ?? "final",
    // Операция — тоже работа: «Окно» и «Гребенка» на одном артикуле, размере и
    // адресате — разные передачи. Без неё в ключе группа смешивала их, а этап
    // в шапке печатался прочерком: сводная строка обещала одну работу, за
    // которой стояли две.
    task.operation_name ?? "",
  ].join("|");
}

function sameValue<T>(rows: ReadyToTransferTask[], pick: (row: ReadyToTransferTask) => T): T | null {
  const [first] = rows;
  const value = pick(first);
  return rows.every((row) => pick(row) === value) ? value : null;
}

export function groupReadyTransfers(items: ReadyToTransferTask[]): ReadyTransferRowItem[] {
  const buckets = new Map<string, ReadyToTransferTask[]>();

  for (const task of items) {
    const key = readyTransferGroupKey(task);
    const bucket = buckets.get(key);
    if (bucket) {
      bucket.push(task);
    } else {
      buckets.set(key, [task]);
    }
  }

  const blocks: ReadyTransferRowItem[] = [];

  for (const [key, rows] of buckets) {
    if (rows.length < 2) {
      blocks.push({ kind: "single", row: rows[0] });
      continue;
    }

    let totalTransferable = 0;
    let totalPlanned = 0;
    let totalAlreadyTransferred = 0;
    let allFinal = true;
    for (const row of rows) {
      const value = parseFloat(row.transferable_quantity);
      if (Number.isFinite(value)) totalTransferable += value;
      const planned = parseFloat(row.planned_quantity);
      if (Number.isFinite(planned)) totalPlanned += planned;
      const transferred = parseFloat(row.already_transferred_quantity);
      if (Number.isFinite(transferred)) totalAlreadyTransferred += transferred;
      if (!isFinalReadyRow(row)) allFinal = false;
    }

    blocks.push({
      kind: "group",
      key,
      productSku: rows[0].product_sku,
      sectionId: rows[0].section_id,
      nextSectionId: rows[0].next_section_id,
      rows,
      totalTransferable,
      totalPlanned,
      totalAlreadyTransferred,
      allFinal,
      hasNextStep: rows[0].has_next_step,
      common: {
        dimensionsLabel: sameValue(rows, (row) => formatDimensionsLabel(row.dimensions, row.dimensions_label)),
        sectionName: sameValue(rows, (row) => row.section_name),
        operationName: sameValue(rows, (row) => row.operation_name),
        nextOperationName: sameValue(rows, (row) => row.next_operation_name),
        nextSectionName: sameValue(rows, (row) => row.next_section_name),
      },
    });
  }

  return clusterByArticle(blocks, {
    articleOf: blockSku,
    quantityOf: (block) =>
      block.kind === "group"
        ? block.totalTransferable
        : parseFloat(block.row.transferable_quantity) || 0,
  });
}

/**
 * Раскладка ready-списка по ГХП: строки одного ГХП идут подряд, внутри ГХП
 * сохраняется обычная группировка (`groupReadyTransfers`).
 *
 * Нужна режиму «Все ГХП»: сервер сортирует ready по `sequence` маршрута, и
 * строки разных ГХП перемешиваются — одинаковые этапы стоят рядом, хотя
 * относятся к разным группам. Артикульный порядок внутри ГХП остаётся:
 * одинаковые артикулы по-прежнему читаются одним куском, но не перетягивают
 * строки через границу ГХП.
 *
 * Участок без ГХП получает отдельный блок «Без ГХП» и уходит в конец, чтобы
 * не вклиниваться между известными группами.
 */
export function groupReadyTransfersBySpg(
  items: ReadyToTransferTask[],
  spgOf: (task: ReadyToTransferTask) => ReadyTransferSpg | null,
): ReadyTransferSpgSection[] {
  const buckets = new Map<string, { spg: ReadyTransferSpg; rows: ReadyToTransferTask[] }>();

  for (const task of items) {
    const spg = spgOf(task) ?? UNKNOWN_SPG;
    const bucket = buckets.get(spg.key);
    if (bucket) {
      bucket.rows.push(task);
    } else {
      buckets.set(spg.key, { spg, rows: [task] });
    }
  }

  return [...buckets.values()]
    .sort((a, b) => a.spg.sortOrder - b.spg.sortOrder)
    .map(({ spg, rows }) => ({ spg, items: groupReadyTransfers(rows) }));
}

/** Артикул блока: у группы он свой, у одиночной строки — из задания. */
function blockSku(block: ReadyTransferRowItem): string {
  return block.kind === "group" ? (block.productSku ?? "—") : (block.row.product_sku ?? "—");
}
