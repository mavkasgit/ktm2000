import { AlertCircle, CheckCircle, SkipForward } from "lucide-react";
import type { CatalogExcelApplyResult } from "@/shared/api/products";

export function ImportResultStep({ result }: { result: CatalogExcelApplyResult }) {
  const { imported, updated, skipped, pairs_created, errors } = result;

  return (
    <>
      <div className="flex flex-wrap gap-2 text-sm">
        <span className="text-green-700 font-medium flex items-center gap-1">
          <CheckCircle className="h-4 w-4" /> Создано: {imported}
        </span>
        <span className="text-blue-700 font-medium flex items-center gap-1">
          <AlertCircle className="h-4 w-4" /> Обновлено: {updated}
        </span>
        <span className="text-muted-foreground flex items-center gap-1">
          <SkipForward className="h-4 w-4" /> Пропущено: {skipped}
        </span>
        {pairs_created > 0 && (
          <span className="text-purple-700 font-medium flex items-center gap-1">
            <CheckCircle className="h-4 w-4" /> Пар связано: {pairs_created}
          </span>
        )}
      </div>

      {errors.length > 0 && (
        <div className="border border-red-200 bg-red-50 rounded-lg max-h-48 overflow-auto px-3 py-2 text-sm">
          <div className="font-medium text-red-800 mb-1">Ошибки строк (строки пропущены):</div>
          <ul className="list-disc list-inside space-y-0.5 text-red-700">
            {errors.map((err, idx) => (
              <li key={idx}>
                Строка {err.row}{err.sku ? ` — ${err.sku}` : ""}: {err.message}
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}
