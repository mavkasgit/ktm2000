#!/usr/bin/env node
// Правила журнала доказательств (docs/quality/proven-checks.json) в одном месте,
// чтобы гейт и `npm run prove-checks` не расходились в трактовке сроков (#357).
//
// Чистые функции: ни файлов, ни часов внутри — дату «сегодня» передаёт вызывающий.
// Так порог 180 дней и просрочка проверяются юнитами (`proof-coverage-core.test.js`),
// а не только прогоном на живом дереве.

/** Дата без времени: `YYYY-MM-DD` — единственный формат в журнале. */
export const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Сколько дней запись может не пересматривать. Полгода — порог из
 * `docs/quality/criteria.md`: запись без обзора не становится ложью сама по
 * себе, поэтому это warn, а не red.
 */
export const MAX_AGE_DAYS = 180;

/** Полночь UTC от `YYYY-MM-DD`, либо null, если формат не тот. */
export function parseDate(value) {
  if (typeof value !== "string" || !DATE_RE.test(value)) return null;
  const stamp = Date.parse(`${value}T00:00:00Z`);
  return Number.isNaN(stamp) ? null : stamp;
}

/** Возраст записи в днях; null — дата не разбирается. */
export function daysSince(value, today) {
  const stamp = parseDate(value);
  if (stamp === null) return null;
  const todayStamp = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate());
  return Math.floor((todayStamp - stamp) / 86_400_000);
}

/** Срок в прошлом (вчера и раньше): `expires` — жёсткая дата, а не пожелание. */
export function isExpired(value, today) {
  const age = daysSince(value, today);
  return age !== null && age > 0;
}

/**
 * Разбор журнала.
 *
 * `steps` — шаги гейта, для которых обязано быть доказательство или исключение.
 * Возвращает:
 *   problems  — журнал сломан (формат даты, истёкший срок, исключение без
 *               причины или без условия): красное при любом флаге, иначе
 *               «бессрочное исключение» снова станет невидимым;
 *   warnings  — обзор старше порога: строка в отчёте, но не красное;
 *   uncovered — шагов нет ни в steps{}, ни в exempt{} (решает вызывающий:
 *               в strict — красное);
 *   exempt/covered — счётчики для строки итога.
 */
export function checkProofCoverage(record, { steps = [], today = new Date() } = {}) {
  const problems = [];
  const warnings = [];
  const exempt = record?.exempt && typeof record.exempt === "object" ? record.exempt : {};
  const proved = record?.steps && typeof record.steps === "object" ? record.steps : {};

  for (const [name, entry] of Object.entries(exempt)) {
    const at = `exempt ${name}`;
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
      problems.push(`${at}: запись должна быть объектом с reason, reviewed, expires`);
      continue;
    }
    if (typeof entry.reason !== "string" || entry.reason.trim() === "") {
      problems.push(`${at}: без reason — исключение без причины не считается`);
    }
    // Условие, при котором доказательство станет возможным, а не «отложено»:
    // без него исключение нельзя пересмотреть, не перечитав весь контекст.
    if (typeof entry.becomes_possible !== "string" || entry.becomes_possible.trim() === "") {
      problems.push(`${at}: без becomes_possible — назовите условие, при котором шаг доказуем`);
    }
    const reviewedAge = daysSince(entry.reviewed, today);
    if (reviewedAge === null) {
      problems.push(`${at}: reviewed должен быть YYYY-MM-DD, а не «${entry.reviewed ?? ""}»`);
    } else if (reviewedAge > MAX_AGE_DAYS) {
      warnings.push(`${at}: обзор не подтверждали ${reviewedAge} дней (${entry.reviewed})`);
    }
    const expiresAge = daysSince(entry.expires, today);
    if (expiresAge === null) {
      problems.push(`${at}: expires должен быть YYYY-MM-DD, а не «${entry.expires ?? ""}»`);
    } else if (expiresAge > 0) {
      problems.push(
        `${at}: срок истёк ${entry.expires} (${expiresAge} дн. назад) — сделайте шаг доказуемым или продлите осознанно`,
      );
    }
  }

  const uncovered = steps.filter((name) => !proved[name] && !exempt[name]);

  return {
    problems,
    warnings,
    uncovered,
    exemptCount: Object.keys(exempt).length,
    coveredCount: steps.filter((name) => proved[name] || exempt[name]).length,
    total: steps.length,
  };
}

/** Строка итога: одна для гейта и для пробника, чтобы формулировки не разъезжались. */
export function summarize(result) {
  const parts = [`${result.coveredCount}/${result.total} шагов с доказанным красным ходом`];
  if (result.exemptCount) parts.push(`${result.exemptCount} в исключениях со сроком`);
  if (result.warnings.length) parts.push(`${result.warnings.length} просроченных обзоров`);
  return parts.join(", ");
}
