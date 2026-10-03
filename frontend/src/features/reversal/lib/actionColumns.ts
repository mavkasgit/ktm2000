/**
 * Описание колонок журнала «Отмена действий» — единственное место, где
 * объявляется, что это за колонка, как она фильтруется и каким параметром
 * уезжает в запрос (#309, ADR-0030, ADR-0037/0038).
 *
 * Сервер `GET /api/actions` понимает ровно два фильтра — `action_type` и
 * `status` (`backend/app/reversal/api.py`), и жёстко сортирует
 * `order_by(Action.id.desc())`: параметра сортировки у него нет. Поэтому
 * `filterField` объявлен у двух колонок, `sortField` — ни у одной, а колонки
 * без фильтра объявлены просто подписью, без флага «ничего не отправляет».
 */
import type { ColumnSpec } from "@/shared/lib/columnSpecs";
import type { RowTone } from "@/shared/lib/rowTones";
import { actionJournalLabels } from "@/shared/lib/generated-labels";

/** Фильтруемые колонки журнала: ровно те, что понимает сервер. */
export type ActionFilterField = "actionType" | "status";

export type ActionColumn = ColumnSpec<ActionFilterField> & {
  id: string;
  label: string;
  /** Класс `<th>` сверх общего: ширина и выравнивание. */
  headerClassName?: string;
};

/**
 * Подпись типа действия по коду вида `transfer_send`. Неизвестный код
 * показывается как есть: сервер отдаёт строкой, и новый вид действия в бэке не
 * должен ни ронять раздел, ни печататься пустотой.
 */
export function actionTypeLabel(actionType: string): string {
  return actionJournalLabels[actionType] ?? actionType;
}

/**
 * Подпись статуса. Она же уходит в фильтр колонки, поэтому живёт здесь, а не
 * тернарником в шапке: фильтр предлагал бы «Отменено», а в строке стояло бы
 * что-то другое.
 */
const STATUS_LABELS: Record<string, string> = {
  active: "Активно",
  reversed: "Отменено",
  amended: "Изменено",
  purged: "Очищено",
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

/**
 * Тон строки по статусу действия (#309).
 *
 * Тон — не «цвет статуса», а ответ на вопрос «можно ли с этим действием ещё
 * что-то сделать»: `active` — живая, её отменяют; `amended` — вмешались;
 * `reversed` — погашена (зачёркивание приезжает из `ROW_TONE_TEXT.completed`);
 * `purged` — ждёт разбора. Неизвестный статус получает `plain`: новый статус
 * в бэке не должен красить строку наугад.
 */
const STATUS_TONES: Record<string, RowTone> = {
  active: "active",
  amended: "activeRunning",
  reversed: "completed",
  purged: "waiting",
};

export function getActionTone(status: string): RowTone {
  return STATUS_TONES[status] ?? "plain";
}

/**
 * Вариант бейджа статуса. Подпись и цвет живут рядом по одной причине: в
 * журнале их читали в двух разных словарях, и «Очищено» могло оказаться
 * зелёным рядом с «Активно».
 */
const STATUS_BADGE_VARIANTS: Record<string, "success" | "secondary" | "warning"> = {
  active: "success",
  amended: "warning",
  reversed: "secondary",
  purged: "secondary",
};

/**
 * Бейдж статуса строки. Статус приходит с сервера строкой: без фолбэка
 * незнакомое значение (новый статус в бэке) уронило бы весь раздел в
 * errorElement, а не одну ячейку.
 */
export function statusBadge(status: string): {
  label: string;
  variant: "success" | "secondary" | "warning";
} {
  return { label: statusLabel(status), variant: STATUS_BADGE_VARIANTS[status] ?? "secondary" };
}

/**
 * Общий кусок класса шапки для колонок с фильтром: попапер занимает всю
 * ячейку, и штатный отступ `p-2` из `DATA_TABLE_STYLES.headerCell` развёл бы
 * его с подписью соседних колонок.
 */
const filterable = "p-0 text-left";

/**
 * Порядок колонок совпадает с порядком в шапке и в теле таблицы. Служебная
 * колонка «Операции» объявлена здесь же, иначе `map` по описанию её потерял бы.
 */
export const actionColumns: ActionColumn[] = [
  {
    id: "id",
    label: "ID",
    headerClassName: "w-[6%]",
    // Номера не фильтруются: `action_id` в контракте `GET /api/actions` нет,
    // и попапер молчал бы, никуда не уехав.
  },
  {
    id: "actionType",
    label: "Действие",
    headerClassName: `${filterable} w-[20%]`,
    filterField: "actionType",
    apiParam: "action_type",
    // Оператор выбирает вид действия из списка, а не ищет подстроку в подписи.
    exactMatch: true,
    valueLabel: actionTypeLabel,
  },
  { id: "object", label: "Объект", headerClassName: "w-[10%]" },
  { id: "actor", label: "Инициатор", headerClassName: "w-[16%]" },
  {
    id: "status",
    label: "Статус",
    headerClassName: `${filterable} w-[12%]`,
    filterField: "status",
    apiParam: "status",
    exactMatch: true,
    valueLabel: statusLabel,
  },
  {
    id: "createdAt",
    label: "Создано",
    headerClassName: "w-[16%]",
    // Фильтра и сортировки нет и не будет: сервер отдаёт порядок `id desc` и
    // не принимает диапазон дат.
  },
  { id: "operations", label: "Операции", headerClassName: "w-[10%] text-right" },
];
