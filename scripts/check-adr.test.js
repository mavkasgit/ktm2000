/**
 * Тесты логики проверки ADR из scripts/check-adr-core.js.
 *
 * Запуск: npm run test:scripts (node --test, без внешних зависимостей).
 * Данные — короткие тексты заголовков и меты, какие реально встречаются в
 * `docs/adr/`: новый шаблон `# ADR-0067: …`, старый `# 0038. …`, заголовок без
 * номера, файл без «Дата:».
 *
 * Класс ошибок, против которого написаны проверки, — коллизия 2026-11-02:
 * два файла с номером 0067, и ни один инструмент на это не жаловался (#390).
 */

"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  inspectAdrFiles,
  numberFromName,
  numberFromTitle,
  headingOf,
  hasMeta,
} = require("./check-adr-core");

/** Файл в шаблоне: имя, заголовок с тем же номером, мета в первых строках. */
function good(name, number) {
  return {
    name,
    path: `docs/adr/${name}`,
    text: `# ADR-${number}: Решение\n\nДата: 2026-11-03. Статус: принято.\n\n## Контекст\n`,
  };
}

const NO_LEGACY = { adopted: "2026-11-03", files: [] };

test("корректный набор не даёт находок", () => {
  const files = [
    good("0001-odno.md", "0001"),
    good("0002-dva.md", "0002"),
  ];
  assert.deepEqual(inspectAdrFiles(files, NO_LEGACY), []);
});

test("дубль номера называется обоими файлами", () => {
  const files = [
    good("0067-pervyy.md", "0067"),
    good("0067-vtoroy.md", "0067"),
  ];
  const findings = inspectAdrFiles(files, NO_LEGACY);
  assert.equal(findings.length, 1);
  assert.equal(findings[0].code, "duplicate-number");
  assert.equal(findings[0].path, "docs/adr/0067-vtoroy.md");
  assert.match(findings[0].message, /дубль номера ADR-0067/);
  assert.match(findings[0].message, /0067-pervyy/);
});

test("номер в заголовке сверяется с именем файла", () => {
  const files = [
    {
      name: "0068-titul-drugoy.md",
      path: "docs/adr/0068-titul-drugoy.md",
      text: "# ADR-0067: Тот же номер, другое решение\n\nДата: 2026-11-03. Статус: принято.\n",
    },
  ];
  const findings = inspectAdrFiles(files, NO_LEGACY);
  assert.deepEqual(findings.map((f) => f.code), ["number-mismatch"]);
  assert.match(findings[0].message, /ADR-0067/);
  assert.match(findings[0].message, /ADR-0068/);
});

test("отсутствие «Дата:» и «Статус:» — две отдельные находки", () => {
  const files = [
    {
      name: "0069-bez-mety.md",
      path: "docs/adr/0069-bez-mety.md",
      text: "# ADR-0069: Решение без меты\n\n## Контекст\n",
    },
  ];
  const findings = inspectAdrFiles(files, NO_LEGACY);
  assert.deepEqual(findings.map((f) => f.code).sort(), ["missing-meta", "missing-meta"]);
});

test("старый заголовок без префикса ADR — находка о форме", () => {
  const files = [
    {
      name: "0070-staryy-formata.md",
      path: "docs/adr/0070-staryy-formata.md",
      text: "# 0070. Старый вид заголовка\n\nДата: 2026-09-24. Статус: принято.\n",
    },
  ];
  const findings = inspectAdrFiles(files, NO_LEGACY);
  assert.deepEqual(findings.map((f) => f.code), ["heading-form"]);
});

test("исключение снимает требования к форме и мете, но не к уникальности", () => {
  const legacyFile = {
    name: "0071-staroe.md",
    path: "docs/adr/0071-staroe.md",
    text: "# Старое решение без номера\n\nабзац\n",
  };
  const legacy = { adopted: "2026-11-03", files: [legacyFile.path] };
  assert.deepEqual(inspectAdrFiles([legacyFile], legacy), []);

  const duplicated = [legacyFile, good("0071-novoe.md", "0071")];
  const findings = inspectAdrFiles(duplicated, { ...legacy, files: [legacyFile.path] });
  assert.deepEqual(findings.map((f) => f.code), ["duplicate-number"]);
});

test("исключение, потерявшее силу, — находка, а не тишина", () => {
  const fixed = good("0072-isopravleno.md", "0072");
  const findings = inspectAdrFiles([fixed], {
    adopted: "2026-11-03",
    files: ["docs/adr/0072-isopravleno.md"],
  });
  assert.deepEqual(findings.map((f) => f.code), ["legacy-stale"]);
});

test("исключение на несуществующий файл — находка", () => {
  const findings = inspectAdrFiles([good("0073-est.md", "0073")], {
    adopted: "2026-11-03",
    files: ["docs/adr/0099-net.md"],
  });
  assert.deepEqual(findings.map((f) => f.code), ["legacy-missing"]);
});

test("имя без четырёх цифр — находка о имени", () => {
  const findings = inspectAdrFiles(
    [{ name: "bez-nomera.md", path: "docs/adr/bez-nomera.md", text: "# Без номера\n" }],
    NO_LEGACY,
  );
  assert.deepEqual(findings.map((f) => f.code), ["bad-name"]);
});

test("вспомогательные функции разбирают оба вида заголовка", () => {
  assert.equal(numberFromName("0067-zakreplennye-kolonki.md"), "0067");
  assert.equal(numberFromName("README.md"), null);
  assert.equal(numberFromTitle("# ADR-0067: Решение\n"), "0067");
  assert.equal(numberFromTitle("# 0038. Старый вид\n"), "0038");
  assert.equal(numberFromTitle("# Просто заголовок\n"), null);
  assert.equal(headingOf("текст\n# ADR-0001: Решение\n"), "# ADR-0001: Решение");
  assert.equal(hasMeta("Дата: 2026-11-03.\n", "Дата:"), true);
  // Мета за пределами окна не считается: она должна быть в шапке, а не в теле.
  assert.equal(hasMeta(`\n\n\n\n\n\n\n\n\n\n\n\nДата: 2026-11-03.\n`, "Дата:"), false);
});
