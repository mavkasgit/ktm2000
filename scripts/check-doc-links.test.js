/**
 * Тесты логики ссылок из scripts/check-doc-links-core.js.
 *
 * Запуск: npm run test:scripts (node --test, без внешних зависимостей).
 * Данные — строки markdown, собранные из форм, которые реально встречаются в
 * доках репозитория: относительные ссылки из корня и из вложенных папок,
 * якоря, внешние URL, ссылки на каталоги, путь с пробелом в имени файла.
 */

"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  isCheckable,
  stripFragment,
  extractTargets,
  resolveTarget,
  collectDirectories,
  findBrokenLinks,
} = require("./check-doc-links-core");

test("isCheckable: схемы и якоря не проверяем, относительные пути — да", () => {
  assert.equal(isCheckable("https://example.com"), false);
  assert.equal(isCheckable("mailto:a@b.c"), false);
  assert.equal(isCheckable("#раздел"), false);
  assert.equal(isCheckable(""), false);
  assert.equal(isCheckable("../AGENTS.md"), true);
  assert.equal(isCheckable("docs/adr/"), true);
});

test("stripFragment: якорь и query отбрасываются, чистый путь не трогается", () => {
  assert.equal(stripFragment("f.md#раздел"), "f.md");
  assert.equal(stripFragment("f.md?x=1"), "f.md");
  assert.equal(stripFragment("docs/adr/"), "docs/adr/");
});

test("extractTargets: inline-ссылки, картинки, угловые скобки, заголовок", () => {
  const md = [
    "см. [ADR](../docs/adr/0001-x.md)",
    "![схема](img/plan.png)",
    "цель в скобках: [<цель>](<docs/a b.md>)",
    "[с заголовком](docs/adr/ \"ADR\")",
    "внешний: [GitHub](https://github.com/x/y)",
  ].join("\n");
  assert.deepEqual(extractTargets(md), [
    "../docs/adr/0001-x.md",
    "img/plan.png",
    "docs/a b.md",
    "docs/adr/",
    "https://github.com/x/y",
  ]);
});

test("extractTargets: путь с пробелом не обрезается, пустая цель пропускается", () => {
  const md = ["[план](testdata/Упаковочный план.xlsx)", "[пусто]()"].join("\n");
  assert.deepEqual(extractTargets(md), ["testdata/Упаковочный план.xlsx"]);
});

test("resolveTarget: подъём по .., склейка, независимость от ОС", () => {
  assert.equal(resolveTarget("docs/context-index.md", "../GLOSSARY.md"), "GLOSSARY.md");
  assert.equal(resolveTarget("docs/agents/domain.md", "../adr/"), "docs/adr/");
  assert.equal(resolveTarget("README.md", "docs/adr/0001-x.md"), "docs/adr/0001-x.md");
  assert.equal(resolveTarget("docs/a.md", "./b.md"), "docs/b.md");
  assert.equal(resolveTarget("a/b/c.md", "../../d.md"), "d.md");
});

test("collectDirectories: все предки каждого файла, с хвостовым слэшем", () => {
  const dirs = collectDirectories(["docs/adr/0001-x.md", "README.md"]);
  assert.ok(dirs.has("docs/"));
  assert.ok(dirs.has("docs/adr/"));
  assert.equal(dirs.has("README/"), false);
});

test("findBrokenLinks: чистое дерево не даёт находок", () => {
  const tracked = ["README.md", "docs/context-index.md", "docs/adr/0001-x.md", "GLOSSARY.md"];
  const files = [
    { path: "docs/context-index.md", content: "[глоссарий](../GLOSSARY.md)" },
    { path: "README.md", content: "[adr](docs/adr/) и [штука](docs/adr/0001-x.md)" },
  ];
  assert.deepEqual(findBrokenLinks(files, tracked), []);
});

test("findBrokenLinks: переименованный документ ловится", () => {
  // То, что пропустил бы любой другой workflow: имя в ссылке и на диске разошлось.
  const tracked = ["docs/context-index.md", "GLOSSARY.md"];
  const files = [{ path: "docs/context-index.md", content: "[](../CONTEXT.md)" }];
  const broken = findBrokenLinks(files, tracked);
  assert.equal(broken.length, 1);
  assert.deepEqual(broken[0], {
    file: "docs/context-index.md",
    target: "../CONTEXT.md",
    resolved: "CONTEXT.md",
  });
});

test("findBrokenLinks: якорь и внешняя ссылка не считаются битыми", () => {
  const tracked = ["docs/context-index.md"];
  const files = [
    {
      path: "docs/context-index.md",
      content: "# шапка\n\n[x](#шапка) [y](https://example.com) [z](mailto:a@b.c)",
    },
  ];
  assert.deepEqual(findBrokenLinks(files, tracked), []);
});

test("findBrokenLinks: неотслеживаемый файл считается отсутствующим", () => {
  // Локально файл есть и ссылка выглядит рабочей — в свежем клоне её не будет.
  const broken = findBrokenLinks(
    [{ path: "README.md", content: "[](./notes.md)" }],
    ["README.md"],
  );
  assert.equal(broken.length, 1);
  assert.equal(broken[0].resolved, "notes.md");
});

test("findBrokenLinks: percent-escaping в цели декодируется", () => {
  const tracked = ["README.md", "my doc.md"];
  const files = [{ path: "README.md", content: "[](my%20doc.md)" }];
  assert.deepEqual(findBrokenLinks(files, tracked), []);
});

test("findBrokenLinks: цель с пробелом резолвится, а не обрезается", () => {
  // Реальная форма из frontend/e2e/AGENTS.md.
  const tracked = ["frontend/e2e/AGENTS.md", "frontend/e2e/testdata/Упаковочный план.xlsx"];
  const files = [
    { path: "frontend/e2e/AGENTS.md", content: "[](testdata/Упаковочный план.xlsx)" },
  ];
  assert.deepEqual(findBrokenLinks(files, tracked), []);
});