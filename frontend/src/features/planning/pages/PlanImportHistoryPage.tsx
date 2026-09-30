/**
 * Страница «История импортов плана» (ADR-0054).
 *
 * Отдельный вход вместо карточки на странице плана: прошлый импорт должен быть
 * виден, не проходя через таблицу позиций, а список батчей — не верхняя панель
 * рабочего экрана. Кнопка «История импортов» стоит в шапке страницы «План»,
 * рядом с «Добавить файл»; пункта в боковом меню нет — раздел у истории тот же,
 * «План», что и у самого плана (у истории остатков так же, #232).
 *
 * Список кросс-плановый: батчи всех планов, потому что на странице плана план
 * не выбирается. Подробности — в `PlanImportHistoryPanel`.
 */
import { useIsFetching, useQueryClient } from "@tanstack/react-query";
import { History, RefreshCw } from "lucide-react";

import { BackButton, Button } from "@/shared/ui";
import { queryKeys } from "@/shared/api/queryKeys";
import { PlanImportHistoryPanel } from "../components/PlanImportHistoryPanel";

// Корень ключа файлов импорта: «Обновить» должно обновить и список со
// скрытыми, и видимый — это два кэша (ADR-0056).
const ALL_PLAN_FILES = queryKeys.plan.allFilesRoot();

export function PlanImportHistoryPage() {
  const queryClient = useQueryClient();
  // Шапка принадлежит странице, а не панели: «Обновить» стоит наравне с
  // фильтрами, а панель остаётся таблицей без своей шапки (как у остатков).
  const isFetching = useIsFetching({ queryKey: ALL_PLAN_FILES }) > 0;

  return (
    <>
      <header className="page-header">
        <div className="flex items-start gap-2">
          <BackButton to="/planning" title="К плану" />
          <div>
            <h1 className="page-title flex items-center gap-2">
              <History className="h-6 w-6" />
              История импортов плана
            </h1>
            <p className="page-subtitle">
              Какие файлы загружались в план, когда и с каким итогом — по всем
              планам. «Применить» проводит загруженный батч, «Откатить»
              возвращает план к состоянию до импорта, «Удалить» убирает запись
              из списка.
            </p>
          </div>
        </div>
        <Button
          variant="outline"
          size="sm"
          disabled={isFetching}
          onClick={() => {
            void queryClient.invalidateQueries({ queryKey: ALL_PLAN_FILES });
          }}
        >
          <RefreshCw className="h-4 w-4 mr-1" />
          Обновить
        </Button>
      </header>

      <PlanImportHistoryPanel />
    </>
  );
}
