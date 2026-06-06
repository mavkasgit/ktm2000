import {
  addDays,
  endOfMonth,
  endOfQuarter,
  endOfWeek,
  format,
  startOfMonth,
  startOfQuarter,
  startOfWeek,
  startOfYear,
  subDays,
  subMonths,
} from "date-fns";

export interface DateRangeValue {
  from: string;
  to: string;
}

export interface DateRangePreset {
  key: string;
  label: string;
  getRange: (now?: Date) => DateRangeValue;
}

function toIsoDate(d: Date): string {
  return format(d, "yyyy-MM-dd");
}

function buildPreset(
  key: string,
  label: string,
  resolve: (now: Date) => { from: Date; to: Date },
): DateRangePreset {
  return {
    key,
    label,
    getRange: (now: Date = new Date()) => {
      const { from, to } = resolve(now);
      return { from: toIsoDate(from), to: toIsoDate(to) };
    },
  };
}

export const allTimePreset: DateRangePreset = {
  key: "all",
  label: "Все время",
  getRange: () => ({ from: "", to: "" }),
};

export const defaultDateRangePresets: DateRangePreset[] = [
  allTimePreset,
  buildPreset("today", "Сегодня", (now) => {
    const d = new Date(now);
    d.setHours(0, 0, 0, 0);
    return { from: d, to: d };
  }),
  buildPreset("yesterday", "Вчера", (now) => {
    const y = subDays(now, 1);
    y.setHours(0, 0, 0, 0);
    return { from: y, to: y };
  }),
  buildPreset("last7", "Последние 7 дней", (now) => {
    const to = new Date(now);
    to.setHours(0, 0, 0, 0);
    return { from: subDays(to, 6), to };
  }),
  buildPreset("last30", "Последние 30 дней", (now) => {
    const to = new Date(now);
    to.setHours(0, 0, 0, 0);
    return { from: subDays(to, 29), to };
  }),
  buildPreset("thisWeek", "Текущая неделя", (now) => ({
    from: startOfWeek(now, { weekStartsOn: 1 }),
    to: endOfWeek(now, { weekStartsOn: 1 }),
  })),
  buildPreset("prevWeek", "Прошлая неделя", (now) => {
    const prev = subDays(now, 7);
    return {
      from: startOfWeek(prev, { weekStartsOn: 1 }),
      to: endOfWeek(prev, { weekStartsOn: 1 }),
    };
  }),
  buildPreset("thisMonth", "Текущий месяц", (now) => ({
    from: startOfMonth(now),
    to: endOfMonth(now),
  })),
  buildPreset("prevMonth", "Прошлый месяц", (now) => {
    const prev = subMonths(now, 1);
    return { from: startOfMonth(prev), to: endOfMonth(prev) };
  }),
  buildPreset("thisQuarter", "Текущий квартал", (now) => ({
    from: startOfQuarter(now),
    to: endOfQuarter(now),
  })),
  buildPreset("yearToDate", "С начала года", (now) => ({
    from: startOfYear(now),
    to: now,
  })),
];

export function formatDateRu(iso: string): string {
  if (!iso) return "";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return "";
  const [year, month, day] = iso.split("-");
  if (!year || !month || !day) return "";
  return `${day}.${month}.${year}`;
}

export function parseRuDate(input: string): string | null {
  if (!input) return null;
  const parts = input.split(".");
  if (parts.length !== 3) return null;
  const [day, month, year] = parts;
  if (day.length !== 2 || month.length !== 2 || year.length !== 4) return null;
  const dd = Number(day);
  const mm = Number(month);
  const yyyy = Number(year);
  if (!Number.isFinite(dd) || !Number.isFinite(mm) || !Number.isFinite(yyyy)) return null;
  if (mm < 1 || mm > 12) return null;
  if (dd < 1 || dd > 31) return null;
  if (yyyy < 1900 || yyyy > 9999) return null;
  const probe = new Date(yyyy, mm - 1, dd);
  if (
    probe.getFullYear() !== yyyy ||
    probe.getMonth() !== mm - 1 ||
    probe.getDate() !== dd
  ) {
    return null;
  }
  return `${year}-${month}-${day}`;
}

export function formatInputDigits(raw: string): string {
  const digits = raw.replace(/\D/g, "").slice(0, 8);
  let result = "";
  for (let i = 0; i < digits.length; i++) {
    if (i === 2 || i === 4) result += ".";
    result += digits[i];
  }
  return result;
}

export function matchesPreset(range: DateRangeValue, preset: DateRangePreset): boolean {
  const expected = preset.getRange();
  if (preset.key === "all") {
    return !range.from && !range.to;
  }
  return range.from === expected.from && range.to === expected.to;
}

export function findActivePreset(
  range: DateRangeValue,
  presets: DateRangePreset[] = defaultDateRangePresets,
): DateRangePreset | null {
  for (const preset of presets) {
    if (matchesPreset(range, preset)) return preset;
  }
  return null;
}

export function isValidRange(from: string, to: string): boolean {
  if (!from || !to) return true;
  return from <= to;
}

export function addDaysIso(iso: string, days: number): string {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return "";
  return toIsoDate(addDays(new Date(y, m - 1, d), days));
}
