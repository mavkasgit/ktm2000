/**
 * Параметры списка бэкапов собираются из описания колонок: пока сборка стояла
 * в `buildBackupsQueryParams` шестью вызовами `pickColumnApiValue` по имени
 * колонки, а «—» и нечисловой размер отбрасывались вручную, седьмая колонка
 * потребовала бы правки сборщика (#198, ADR-0038).
 */
import { describe, expect, it } from "vitest";

import { buildColumnApiParams } from "@/shared/lib/columnSpecs";

import { backupColumns, type BackupSortField } from "./backupColumns";

const build = (
  columnFilters: Partial<Record<BackupSortField, Set<string>>>,
  columnSearchQueries: Partial<Record<BackupSortField, string>> = {},
) => buildColumnApiParams(columnFilters, columnSearchQueries, backupColumns);

describe("параметры списка бэкапов", () => {
  it("выбранное значение каждой колонки уезжает под своим именем", () => {
    const params = build({
      filename: new Set(["dump-2026-09-27.sql"]),
      db_name: new Set(["ktm2000"]),
      backup_type: new Set(["monthly"]),
      size: new Set(["1024"]),
      created_at: new Set(["2026-09-27T03:00:00Z"]),
      comment: new Set(["перед обновлением"]),
    });

    expect(params).toEqual({
      filename: "dump-2026-09-27.sql",
      db_name: "ktm2000",
      backup_type: "monthly",
      size: "1024",
      created_at: "2026-09-27T03:00:00Z",
      comment: "перед обновлением",
    });
  });

  it("«—» в комментарии — это пусто, а не значение", () => {
    // Пустые комментарии показываются в поповере как «—», но сервер такого
    // значения не понимает: уехавшее «—» отфильтровало бы список не по тому,
    // что выбрал оператор.
    expect(build({ comment: new Set(["—"]) })).toEqual({});
  });

  it("размер уезжает числом, а нечисловой ввод в запрос не уходит", () => {
    expect(build({ size: new Set(["1024"]) }).size).toBe("1024");
    expect(build({ size: new Set(["не 1024"]) })).toEqual({});
  });

  it("колонка без выбора в запрос не уезжает", () => {
    expect(build({ filename: new Set(["dump.sql"]) })).toEqual({ filename: "dump.sql" });
  });

  it("поисковый запрос колонки уезжает подстрокой, если значения не выбраны", () => {
    expect(build({}, { db_name: "ktm" })).toEqual({ db_name: "ktm" });
  });

  it("ни одна колонка не clientOnly: все шесть фильтрует сервер", () => {
    // Клиентская колонка сборщиком пропускается. Здесь такой нет, и это
    // объявлено явно: значение каждой колонки обязано доезжать до сервера
    // отдельным параметром, а не висеть на доске.
    expect(backupColumns.filter((column) => column.clientOnly)).toEqual([]);
  });
});
