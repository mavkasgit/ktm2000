/**
 * Логика проверки каталога ADR: уникальность номеров, соответствие номера в
 * заголовке номеру файла, наличие «Дата:» и «Статус:».
 *
 * Вынесено из CLI, чтобы тестировалось без чтения ФС — как
 * `check-doc-links-core.js`. Запуск тестов: `npm run test:scripts`.
 *
 * Почему это отдельная проверка, а не часть `check-doc-links`: ссылки резолвятся
 * по `git ls-files`, и битого указателя в коллизии номеров нет — оба файла
 * существуют, оба открываются. Ломается смысл цитаты: «ADR-0067» означал и
 * мобильную таблицу, и импортный артикул (#390). Такую ошибку нельзя увидеть
 * глазами по диффу одного файла, поэтому правило машинное.
 */

"use strict";

/** Четыре цифры в начале имени файла — идентификатор решения. */
const NAME_NUMBER = /^(\d{4})-/;
/** Номер в заголовке: `# ADR-0067: …`, допустим и старый вид `# 0038. …`. */
const TITLE_NUMBER = /^#\s*(?:ADR-)?(\d{4})(?=[.:])/;
/** Обязательная форма заголовка нового решения. */
const TITLE_FORM = /^#\s*ADR-(\d{4}):/;
/** Служебные строки искали в первых строках файла, а не во всём тексте. */
const META_WINDOW = 12;

/** Номер, который файлу присвоено имя. */
function numberFromName(name) {
  const match = NAME_NUMBER.exec(name);
  return match ? match[1] : null;
}

/** Номер в первой строке-заголовке (или null, если заголовок без номера). */
function numberFromTitle(text) {
  const first = text.split(/\r?\n/).find((line) => line.startsWith("# ")) ?? "";
  const match = TITLE_NUMBER.exec(first);
  return match ? match[1] : null;
}

/** Первая строка-заголовок файла. */
function headingOf(text) {
  return text.split(/\r?\n/).find((line) => line.startsWith("# ")) ?? "";
}

function hasMeta(text, label) {
  const head = text.split(/\r?\n/).slice(0, META_WINDOW).join("\n");
  return head.includes(label);
}

/**
 * Основной разбор: по списку `{ name, path, text }` и списку датированных
 * исключений `{ adopted, files }` возвращает находки `{ code, path, message }`.
 *
 * Исключения нужны, чтобы проверка была зелёной с первого дня, а не «отложенной
 * на потом»: восемь старых ADR написаны до единого шаблона. Право на исключение
 * даёт только запись в файле репозитория — новый файл молча в неё не попадёт,
 * правка списка видна в дифе.
 */
function inspectAdrFiles(files, legacy) {
  const findings = [];
  const exempt = new Set(legacy.files);
  const seen = new Map();

  for (const file of files) {
    const nameNumber = numberFromName(file.name);
    if (nameNumber === null) {
      findings.push({
        code: "bad-name",
        path: file.path,
        message: "имя файла ADR должно начинаться с четырёх цифр и дефиса",
      });
      continue;
    }

    const previous = seen.get(nameNumber);
    if (previous !== undefined) {
      findings.push({
        code: "duplicate-number",
        path: file.path,
        message: `дубль номера ADR-${nameNumber}: второй файл после ${previous}`,
      });
    } else {
      seen.set(nameNumber, file.path);
    }

    const titleNumber = numberFromTitle(file.text);
    if (titleNumber !== null && titleNumber !== nameNumber) {
      findings.push({
        code: "number-mismatch",
        path: file.path,
        message: `номер в заголовке (ADR-${titleNumber}) не совпадает с именем файла (ADR-${nameNumber})`,
      });
    }

    if (exempt.has(file.path)) continue;

    if (!TITLE_FORM.test(headingOf(file.text))) {
      findings.push({
        code: "heading-form",
        path: file.path,
        message: "заголовок должен быть вида `# ADR-0000: <решение>`",
      });
    }
    for (const label of ["Дата:", "Статус:"]) {
      if (!hasMeta(file.text, label)) {
        findings.push({
          code: "missing-meta",
          path: file.path,
          message: `в первых ${META_WINDOW} строках нет «${label}»`,
        });
      }
    }
  }

  const present = new Set(files.map((file) => file.path));
  for (const listed of legacy.files) {
    if (!present.has(listed)) {
      findings.push({
        code: "legacy-missing",
        path: listed,
        message: "исключение ссылается на файл, которого нет в каталоге",
      });
      continue;
    }
    const file = files.find((candidate) => candidate.path === listed);
    const clean =
      TITLE_FORM.test(headingOf(file.text)) &&
      hasMeta(file.text, "Дата:") &&
      hasMeta(file.text, "Статус:");
    if (clean) {
      findings.push({
        code: "legacy-stale",
        path: listed,
        message: "файл привели к шаблону — исключение больше не нужно, удалите его",
      });
    }
  }

  return findings;
}

module.exports = {
  inspectAdrFiles,
  numberFromName,
  numberFromTitle,
  headingOf,
  hasMeta,
  META_WINDOW,
};
