"use strict";
/**
 * Разбор свежести закреплённых инструментов (#368). Чистая функция: даты и
 * факты приходят параметрами, сети и файловой системы здесь нет — поэтому
 * все состояния проверяются юнит-тестами, а CLI только их собирает.
 *
 * Пороги унаследованы от донора (mokevnin/dev-quality-gates): `push` — возраст,
 * после которого пора посмотреть (90 дней), `review` — точно пора (180),
 * `release` — инструмент не обновляли дольше, чем живёт крупный релиз (365).
 * Разница с донором: флаг даёт худшее из двух измерений (пин не трогали /
 * запись не пересматривали), а не два сообщения подряд об одном и том же.
 */

const { isoDate } = require("./format-utils");

const DEFAULT_THRESHOLDS = { push: 90, review: 180, release: 365 };

const DAY_MS = 86400000;

/** Целое число дней между двумя ISO-датами; отсутствующая дата = 0 дней. */
function daysBetween(fromIso, toIso) {
  if (!fromIso || !toIso) return 0;
  const from = Date.parse(fromIso);
  const to = Date.parse(toIso);
  if (Number.isNaN(from) || Number.isNaN(to)) return 0;
  return Math.max(0, Math.round((to - from) / DAY_MS));
}

function levelForAge(age, thresholds) {
  if (age > thresholds.release) return "fail";
  if (age > thresholds.review) return "warn";
  return null;
}

/** commit-sha в пине (SHA-pinned actions) — с тегом не сопоставляется. */
function looksLikeSha(value) {
  return /\b[0-9a-f]{40}\b/.test(String(value || ""));
}

/**
 * Числовая часть версии без префиксов диапазона: `^5.7.2` → `5.7.2`,
 * `>=10` → `10`, `v4.4.0` → `4.4.0`. Не-числовое (`15-alpine`) → null.
 */
function numericVersion(value) {
  const match = /(\d+(?:\.\d+)*)/.exec(String(value || ""));
  if (!match) return null;
  if (looksLikeSha(value)) return null;
  return match[1];
}

function compareNumeric(a, b) {
  const pa = a.split(".").map(Number);
  const pb = b.split(".").map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i += 1) {
    const diff = (pa[i] || 0) - (pb[i] || 0);
    if (diff !== 0) return diff;
  }
  return 0;
}

/**
 * Имя дистрибутива из строки закрепления (`coverage==7.16.2` → `coverage`).
 * Брать его из `name` реестра нельзя: «coverage.py» — человекочитаемое имя, на
 * PyPI такого нет, и 404 выглядел бы как «инструмент не отвечает», хотя не
 * отвечаем мы сами. Версии с операторами диапазона (`>=`) участвуют: пин
 * `alembic>=1.13.0` — тоже закрепление.
 */
function distNameFromPin(text, version) {
  if (!text || !version) return null;
  const want = numericVersion(version);
  if (!want) return null;
  for (const line of String(text).split(/\r?\n/)) {
    const m = /^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:==|>=|<=|~=|!=|===)\s*([^\s#;]+)/.exec(line);
    if (m && numericVersion(m[2]) === want) return m[1];
  }
  return null;
}

/**
 * @param {Array<object>} entries записи реестра с собранными фактами:
 *   `pin_exists`, `pin_committed_at`, `last_reviewed`, опционально `upstream`
 *   ({ latest_version, published_at, archived, renamed_to, error }).
 * @param {{push:number,review:number,release:number}} thresholds
 * @param {string} now ISO-дата «сегодня»
 * @returns {Array<{code:string, level:string, id:string, message:string}>}
 */
function inspectFreshness(entries, thresholds = DEFAULT_THRESHOLDS, now) {
  const findings = [];
  const today = now || isoDate();

  for (const e of entries) {
    const label = e.name || e.id;

    if (!e.pin_exists) {
      findings.push({
        code: "pin-missing",
        level: "fail",
        id: e.id,
        message: `${label}: закреплён в ${e.pinned_in}, но такого файла нет — версия в реестре ни к чему не привязана`,
      });
      continue;
    }

    const pinAge = daysBetween(e.pin_committed_at, today);
    const reviewAge = daysBetween(e.last_reviewed, today);
    const age = Math.max(pinAge, reviewAge);
    const level = levelForAge(age, thresholds);
    if (level) {
      const what =
        pinAge >= reviewAge
          ? `пин в ${e.pinned_in} не трогали ${pinAge} дн.`
          : `запись не пересматривали ${reviewAge} дн.`;
      findings.push({
        code: "pin-stale",
        level,
        id: e.id,
        message: `${label} ${e.version}: ${what} (порог осмотра ${thresholds.review} дн., грубый — ${thresholds.release})`,
      });
    }

    const up = e.upstream;
    if (!up) continue;

    if (up.archived) {
      findings.push({
        code: "archived",
        level: "fail",
        id: e.id,
        message: `${label}: репозиторий ${up.repo || e.id} в архиве — обновляться некуда, нужна замена или осознанная заморозка`,
      });
      continue;
    }

    if (up.renamed_to) {
      findings.push({
        code: "renamed",
        level: "warn",
        id: e.id,
        message: `${label}: ${up.repo || "репозиторий"} переименован в ${up.renamed_to} — пин по старому пути молча перестанет обновляться`,
      });
    }

    if (up.error) {
      findings.push({
        code: "upstream-unknown",
        level: "warn",
        id: e.id,
        message: `${label}: реестр не ответил (${up.error}) — «свеж» в этом прогоне не означает «проверено»`,
      });
      continue;
    }

    const pinned = numericVersion(e.version);
    const latest = numericVersion(up.latest_version);
    if (!pinned || !latest) {
      findings.push({
        code: "uncomparable",
        level: "info",
        id: e.id,
        message: `${label}: закреплено «${e.version}», доступно «${up.latest_version}» — сопоставить числа нельзя (sha-пин или нечисловой тег)`,
      });
      continue;
    }

    if (compareNumeric(latest, pinned) > 0) {
      findings.push({
        code: "newer-upstream",
        level: "warn",
        id: e.id,
        message: `${label}: закреплено ${pinned}, доступно ${latest}${up.published_at ? ` (выпуск ${up.published_at})` : ""}`,
      });
    }
  }

  return findings;
}

module.exports = {
  inspectFreshness,
  daysBetween,
  levelForAge,
  numericVersion,
  looksLikeSha,
  distNameFromPin,
  DEFAULT_THRESHOLDS,
};
