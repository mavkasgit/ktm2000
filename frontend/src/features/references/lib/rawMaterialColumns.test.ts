/**
 * Параметры справочника сырья собираются из описания колонок: пока сборка
 * стояла в `buildRawMaterialsApiParams` и перечисляла колонки руками, седьмая
 * колонка потребовала бы правки этого кода, а опечатка в имени параметра
 * проскочила бы незамеченной — фильтр был бы виден и не фильтровал ничего
 * (#198, ADR-0038).
 *
 * Тест держит контракт запроса, а не существование экспорта: значение
 * колонки должно уехать под своим именем параметра.
 */
import { describe, expect, it } from "vitest";

import {
  buildRawMaterialColumnApiParams,
  rawMaterialColumns,
  type RawMaterialColumnField,
} from "./rawMaterialColumns";

const build = (
  columnFilters: Partial<Record<RawMaterialColumnField, Set<string>>>,
  columnSearchQueries: Partial<Record<RawMaterialColumnField, string>> = {},
) => buildRawMaterialColumnApiParams(columnFilters, columnSearchQueries);

/**
 * Ключи контракта запроса. Сверка идёт с backend: `GET /products` в
 * `backend/app/api/routes/products.py` принимает `sku`, `length_from`,
 * `length_to`, `qty_from`, `qty_to`, `is_paired_profile`, `skip_shot_blast`,
 * `is_laminated`. Значения приходят в типах контракта: длины и количества —
 * числами, флаги — булевыми; род объявляет описание колонки (`paramKind`),
 * приводит сборщик.
 */
const CONTRACT_KEYS = new Set([
  "sku",
  "length_from",
  "length_to",
  "qty_from",
  "qty_to",
  "is_paired_profile",
  "skip_shot_blast",
  "is_laminated",
]);

describe("параметры колонок справочника сырья", () => {
  it("артикул уезжает под своим именем", () => {
    expect(build({ sku: new Set(["RAW-2700"]) })).toEqual({ sku: "RAW-2700" });
  });

  it("«Да» и «Нет» уезжают флагом, а не словом", () => {
    // Список значений — слова для оператора, а `is_paired_profile` в запросе
    // булев: без перекодировки бэкенд получил бы неразбираемый параметр.
    expect(build({ is_paired_profile: new Set(["Да"]) })).toEqual({ is_paired_profile: true });
    expect(build({ is_paired_profile: new Set(["Нет"]) })).toEqual({ is_paired_profile: false });
    expect(build({ skip_shot_blast: new Set(["Да"]) })).toEqual({ skip_shot_blast: true });
    expect(build({ is_laminated: new Set(["Нет"]) })).toEqual({ is_laminated: false });
  });

  it("выбранная длина едет точной границей в обе стороны", () => {
    // Выбор оператора — конкретная длина, а не «от 2700»: сервер получает
    // диапазон, и обе границы названы, иначе фильтр остался бы открытым.
    expect(build({ length_mm: new Set(["2700"]) })).toEqual({
      length_from: 2700,
      length_to: 2700,
    });
  });

  it("выбранное количество едет точной границей в обе стороны", () => {
    expect(build({ quantity_per_hanger: new Set(["50"]) })).toEqual({
      qty_from: 50,
      qty_to: 50,
    });
  });

  it("«—» в количестве параметра не даёт: это отсутствие значения", () => {
    // Раньше «—» отбрасывалось вручную в вызове сборщика; теперь это
    // свойство колонки, и пропустить его нельзя.
    expect(build({ quantity_per_hanger: new Set(["—"]) })).toEqual({});
  });

  it("нечисловой ввод в длине и количестве не уезжает", () => {
    expect(build({ length_mm: new Set(["длинная"]) })).toEqual({});
    expect(build({ quantity_per_hanger: new Set(["много"]) })).toEqual({});
  });

  it("поиск в попапере флага не подменяется ничем: это поиск по списку", () => {
    // Оператор набрал «да» в поиске попапера, но значение не выбрал: флаг без
    // выбора означал бы «просто нечёткое совпадение», а такого параметра у
    // сервера нет.
    expect(build({}, { is_paired_profile: "да" })).toEqual({});
  });

  it("колонка без выбранного значения молчит", () => {
    expect(build({ sku: new Set(), length_mm: new Set() })).toEqual({});
  });

  it("без фильтров параметров не уезжает вовсе", () => {
    expect(build({})).toEqual({});
  });

  it("несколько выбранных значений не уезжают: параметр фильтра один", () => {
    // Мультизначность означала бы «и 50, и 40», но параметр один, и такое
    // значение молча выбирало бы произвольное.
    expect(build({ sku: new Set(["A", "B"]) })).toEqual({});
  });
});

describe("набор параметров совпадает с контрактом запроса", () => {
  it("все выбранные колонки уезжают под именами, которые знает бэкенд", () => {
    const params = build({
      sku: new Set(["RAW-2700"]),
      quantity_per_hanger: new Set(["50"]),
      length_mm: new Set(["2700"]),
      is_paired_profile: new Set(["Да"]),
      skip_shot_blast: new Set(["Нет"]),
      is_laminated: new Set(["Да"]),
    });

    for (const key of Object.keys(params)) {
      expect(CONTRACT_KEYS.has(key), `параметр ${key} не объявлен в GET /products`).toBe(true);
    }
  });

  it("набор колонок покрывает все шесть фильтров экрана", () => {
    // Список колонок и список параметров разошлись бы молча: колонка была бы
    // видна, попапер работал бы, а фильтр не уезжал бы.
    expect(rawMaterialColumns.map((column) => column.filterField)).toEqual([
      "sku",
      "quantity_per_hanger",
      "length_mm",
      "is_paired_profile",
      "skip_shot_blast",
      "is_laminated",
    ]);
  });
});

describe("описание колонок объявляет фильтр и сортировку вместе", () => {
  it("у каждой колонки есть и фильтр, и сортировка", () => {
    // Половина объявления без другой половины — колонка с одной лишь
    // подписью: сервер фильтрует или сортирует её, а оператор не может.
    for (const column of rawMaterialColumns) {
      expect(column.filterField, `у колонки ${column.id} нет фильтра`).toBeDefined();
      expect(column.sortField, `у колонки ${column.id} нет сортировки`).toBeDefined();
    }
  });

  it("у каждой колонки есть подпись и ширина шапки", () => {
    for (const column of rawMaterialColumns) {
      expect(column.label.trim().length, `у колонки ${column.id} пустая подпись`).toBeGreaterThan(0);
      expect(column.headerClassName, `у колонки ${column.id} не задана ширина <th>`).toBeTruthy();
    }
  });

  it("идентификаторы колонок не повторяются", () => {
    // Повторный `key` в `map` по шапке оставил бы оператора с одной колонкой
    // из двух, а вторую — вовсе без шапки.
    const ids = rawMaterialColumns.map((column) => column.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("все поля сортировки колонок сервер сортирует", () => {
    // `_SORT_COLUMNS` в products.py. Незаявленное поле вернуло бы 400 на
    // клик оператора, а подмена чужого поля — молчаливую перестановку не
    // той колонки, которую он нажал.
    const SERVER_SORTED = new Set([
      "id",
      "sku",
      "code",
      "name",
      "type",
      "unit",
      "is_active",
      "is_catalog_item",
      "is_paired_profile",
      "profile_type",
      "alloy",
      "color",
      "anod_type",
      "source",
      "dimension_state",
      "length_mm",
      "quantity_per_hanger",
      "aliases",
      "weight_per_meter",
      "perimeter_mm",
      "mount_width_mm",
      "cross_section",
      "skip_shot_blast",
      "is_laminated",
    ]);
    for (const column of rawMaterialColumns) {
      expect(SERVER_SORTED.has(column.sortField!), `сервер не сортирует по ${column.id}`).toBe(true);
    }
  });
});
