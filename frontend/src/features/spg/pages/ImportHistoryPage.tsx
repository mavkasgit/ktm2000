/**
 * Страница «История импортов остатков» (#232).
 *
 * Отдельный вход вместо секции внутри модалки: прошлый импорт должен быть виден
 * без того, чтобы проходить новый импорт до конца. Пункт в боковое меню не
 * добавлен намеренно — история остатков относится к ГХП, и кнопка «История
 * импортов» стоит на странице ГХП рядом с «Импорт из Excel».
 *
 * Права на чтение и на откат — те же, что у секции в модалке: список отдаёт
 * `READER_ROLES`, откат и скрытие — только админу (ADR-0052 п.6).
 */
import { useIsFetching, useQueryClient } from "@tanstack/react-query";
import { History, RefreshCw } from "lucide-react";

import { BackButton, Button } from "@/shared/ui";
import { queryKeys } from "@/shared/api/queryKeys";
import { ImportHistoryPanel } from "../components/ImportHistoryPanel";

const IMPORT_BATCHES = queryKeys.stock.importBatches();

export function ImportHistoryPage() {
  const queryClient = useQueryClient();
  // Шапка принадлежит странице, а не панели: «Обновить» зеркалит «Передачи» и
  // стоит наравне с фильтрами, а панель остаётся таблицей без своей шапки.
  const isFetching = useIsFetching({ queryKey: IMPORT_BATCHES }) > 0;

  return (
    <>
      <header className="page-header">
        <div className="flex items-start gap-2">
          <BackButton to="/spg" title="К ГХП" />
          <div>
            <h1 className="page-title flex items-center gap-2">
              <History className="h-6 w-6" />
              История импортов остатков
            </h1>
            <p className="page-subtitle">
              Какие остатки заливались в склады, кем и когда. Откат возвращает
              склад к состоянию до импорта; «Убрать из списка» только прячет
              запись, не трогая остатки.
            </p>
          </div>
        </div>
        <Button
          variant="outline"
          size="sm"
          disabled={isFetching}
          onClick={() => {
            void queryClient.invalidateQueries({ queryKey: IMPORT_BATCHES });
          }}
        >
          <RefreshCw className="h-4 w-4 mr-1" />
          Обновить
        </Button>
      </header>

      <ImportHistoryPanel />
    </>
  );
}
