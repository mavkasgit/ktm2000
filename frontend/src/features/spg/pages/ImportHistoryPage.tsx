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
import { ArrowLeft, History } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/shared/ui";
import { ImportHistoryPanel } from "../components/ImportHistoryPanel";

export function ImportHistoryPage() {
  const navigate = useNavigate();

  return (
    <>
      <header className="page-header flex items-start justify-between">
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
        <Button
          variant="outline"
          onClick={() => navigate("/spg")}
          className="flex items-center gap-2"
        >
          <ArrowLeft className="h-4 w-4" />
          К ГХП
        </Button>
      </header>

      <div className="rounded-lg border bg-card p-4">
        <ImportHistoryPanel />
      </div>
    </>
  );
}