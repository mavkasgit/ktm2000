/**
 * Логика проверки мёртвых dev-зависимостей: для каждого devDependency фронтенда
 * — назван ли пакет где-нибудь в отслеживаемых файлах (по имени пакета или по
 * имени его бинарника), и не спрятан ли он в датированных исключениях.
 *
 * Вынесено из CLI, чтобы тестировалось без чтения ФС — как `check-adr-core.js`.
 * Запуск тестов: `npm run test:scripts`.
 *
 * Почему проверка машинная (#374). Утверждение «этот пакет мёртвый» раньше
 * держалось на grep'е по имени и на глаз: `@testing-library/jest-dom` числился
 * мёртвым, пока `vitest.config.ts` не оказался его потребителем — там пакет
 * зовётся через `setupFiles` с подпутём (`@testing-library/jest-dom/vitest`).
 * Одинаково плохи обе ошибки: удалить живое и оставить мёртвое, потому что
 * «в package.json его никто не вызывает». Поэтому ответ проверки — всегда
 * список находок с названным местом поиска, а молчаливое удаление пакета —
 * только решение человека, после зелёного полного прогона тестов.
 */

"use strict";

/** Русская форма счётного слова. */
function plural(count, one, few, many) {
  const tens = count % 100;
  const unit = count % 10;
  if (tens >= 11 && tens <= 14) return many;
  if (unit === 1) return one;
  if (unit >= 2 && unit <= 4) return few;
  return many;
}

/**
 * Назван ли токен в тексте как отдельное имя, а не как кусок чужого.
 *
 * Границы важны в обе стороны и именно они решают, что проверка не врёт:
 *   * `@types/react` внутри `@types/react-dom` — не упоминание: дефис
 *     продолжает имя другого пакета;
 *   * `vite` внутри `vitest` — не упоминание;
 *   * `@testing-library/jest-dom` внутри `@testing-library/jest-dom/vitest` —
 *     упоминание: подпуть это тот же пакет, подключённый из `setupFiles`.
 * Продолжение имени дефисом или словом запрещено, `/` разрешён.
 */
function mentions(text, token) {
  const escaped = token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(^|[^\\w.-])${escaped}($|[^\\w-])`).test(text);
}

/** Ключи манифеста, где имя пакета — объявление, а не использование. */
const DECLARATION_KEYS = [
  "dependencies",
  "devDependencies",
  "peerDependencies",
  "optionalDependencies",
];

/**
 * Текст файла без блоков зависимостей npm-манифеста.
 *
 * Нужен, чтобы проверка не была тавтологией: каждое имя devDependency уже стоит
 * в собственном объявлении в `package.json`, и поиск «по всему дереву» без этого
 * шага даёт «все пакеты живы» при полностью мёртвом наборе. Всё остальное —
 * `scripts`, `lint-staged`, произвольные поля — остаётся: там имя пакета и есть
 * след использования. Невалидный JSON и файлы без блоков зависимостей возвращаются
 * как есть: проверка не должна молча терять содержимое.
 */
function withoutDependencyDeclarations(text) {
  let manifest;
  try {
    manifest = JSON.parse(text);
  } catch {
    return text;
  }
  if (!manifest || typeof manifest !== "object") return text;
  if (!DECLARATION_KEYS.some((key) => manifest[key] && typeof manifest[key] === "object")) {
    return text;
  }
  const copy = { ...manifest };
  for (const key of DECLARATION_KEYS) delete copy[key];
  return JSON.stringify(copy, null, 2);
}

/** Дата сегодня в форме ISO — сравнение исключений по строкам корректно для ISO. */
function isoDate() {
  return new Date().toISOString().slice(0, 10);
}

/**
 * Находки по списку пакетов и содержимому файлов.
 *
 * `packages` — `{ name, bins }`: бинарники CLI читает из установленного
 * `package.json`, потому что зовут инструмент по имени бинарника, а не пакета
 * (`tsc` — это `typescript`). `files` — `{ path, text }`. `allowlist` —
 * `{ adopted, exempt: { "<пакет>": { reason, reviewBy } } }`. `now` — дата
 * «сегодня» в форме ISO (нужна тестам, чтобы не зависеть от часового пояса).
 */
function inspectDevDependencies({ packages, files, allowlist, now = isoDate() }) {
  const findings = [];
  const scope = `проверено ${files.length} ${plural(files.length, "файл", "файла", "файлов")}`;
  const exempt = allowlist.exempt ?? {};

  for (const pkg of packages) {
    const names = [pkg.name, ...(pkg.bins ?? [])];
    const used = files.some(
      (file) => names.some((token) => token && mentions(file.text, token)),
    );
    const entry = exempt[pkg.name];

    if (entry) {
      if (used) {
        findings.push({
          code: "unnecessary",
          name: pkg.name,
          message:
            `пакет назван в отслеживаемых файлах — исключение «${entry.reason}» ` +
            "больше не нужно, удалите его",
        });
      } else if (!entry.reviewBy) {
        findings.push({
          code: "undated",
          name: pkg.name,
          message:
            "у исключения нет поля reviewBy — датированное исключение (#386) " +
            `без даты неотличимо от отключённой проверки (причина: «${entry.reason ?? "не указана"}»)`,
        });
      } else if (entry.reviewBy < now) {
        findings.push({
          code: "expired",
          name: pkg.name,
          message:
            `срок пересмотра исключения истёк (${entry.reviewBy} < ${now}): ` +
            `«${entry.reason}» — пересмотреть или удалять пакет`,
        });
      }
      continue;
    }

    if (!used) {
      findings.push({
        code: "unused",
        name: pkg.name,
        message:
          `ни имя пакета, ни его бинарники (${names.join(", ")}) не названы ` +
          `ни в одном отслеживаемом файле (${scope})`,
      });
    }
  }

  for (const [name, entry] of Object.entries(exempt)) {
    if (packages.some((pkg) => pkg.name === name)) continue;
    findings.push({
      code: "unknown",
      name,
      message:
        `исключение ссылается на пакет «${name}», которого нет в devDependencies ` +
        `(причина: ${entry?.reason ?? "не указана"}) — список устарел`,
    });
  }

  return findings;
}

module.exports = {
  inspectDevDependencies,
  mentions,
  plural,
  isoDate,
  withoutDependencyDeclarations,
  DECLARATION_KEYS,
};
