import { useState, type ReactNode } from "react";
import { CheckCircle, AlertCircle, SkipForward, Image } from "lucide-react";
import { Button } from "@/shared/ui/button";
import type { CatalogPreview } from "@/shared/api/products";

type ActionFilter = "all" | "create" | "update" | "skip";

const ACTION_CONFIG: Record<
  Exclude<ActionFilter, "all">,
  { label: string; icon: ReactNode; color: string }
> = {
  create: {
    label: "Создать",
    icon: <CheckCircle className="h-4 w-4" />,
    color: "bg-green-100 text-green-800",
  },
  update: {
    label: "Обновить",
    icon: <AlertCircle className="h-4 w-4" />,
    color: "bg-blue-100 text-blue-800",
  },
  skip: {
    label: "Пропустить",
    icon: <SkipForward className="h-4 w-4" />,
    color: "bg-gray-100 text-gray-600",
  },
};

export function ImportPreviewContent({ preview }: { preview: CatalogPreview }) {
  const [filter, setFilter] = useState<ActionFilter>("all");

  const { stats } = preview;
  const filteredItems =
    filter === "all"
      ? preview.items
      : preview.items.filter((item) => item.action === filter);

  return (
    <>
      {/* Summary */}
      <div className="flex flex-wrap gap-2 text-sm">
        <span className="text-muted-foreground">
          Всего {stats.total}:
        </span>
        <span className="text-green-700 font-medium">{stats.create} создать</span>
        <span className="text-blue-700 font-medium">{stats.update} обновить</span>
        <span className="text-muted-foreground">{stats.skip} пропустить</span>
        {preview.errors && preview.errors.length > 0 && (
          <span className="text-red-700 font-medium">
            {stats.errors ?? preview.errors.length} строк с ошибками
          </span>
        )}
      </div>

      {/* Row errors report (#63) */}
      {preview.errors && preview.errors.length > 0 && (
        <div className="border border-red-200 bg-red-50 rounded-lg max-h-32 overflow-auto px-3 py-2 text-sm">
          <div className="font-medium text-red-800 mb-1">Ошибки строк (строки пропущены):</div>
          <ul className="list-disc list-inside space-y-0.5 text-red-700">
            {preview.errors.map((err, idx) => (
              <li key={idx}>
                Строка {err.row}{err.sku ? ` — ${err.sku}` : ""}: {err.message}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Filter buttons */}
      <div className="flex gap-1">
        {(["all", "create", "update", "skip"] as ActionFilter[]).map((f) => {
          if (f === "all") {
            return (
              <Button
                key={f}
                variant={filter === "all" ? "default" : "outline"}
                size="sm"
                onClick={() => setFilter("all")}
              >
                Все
              </Button>
            );
          }
          const cfg = ACTION_CONFIG[f];
          return (
            <Button
              key={f}
              variant={filter === f ? "default" : "outline"}
              size="sm"
              onClick={() => setFilter(f)}
            >
              {cfg.icon}
              <span className="ml-1">{cfg.label}</span>
            </Button>
          );
        })}
      </div>

      {/* Table with scroll */}
      <div className="flex-1 overflow-auto border rounded-lg">
        <table className="w-full text-sm">
          <thead className="bg-muted sticky top-0">
            <tr>
              <th className="px-4 py-3 text-left font-medium">Артикул</th>
              <th className="px-4 py-3 text-left font-medium">Длины, мм</th>
              <th className="px-4 py-3 text-left font-medium">Кол-во на подвесе</th>
              <th className="px-4 py-3 text-left font-medium">Фото</th>
              <th className="px-4 py-3 text-left font-medium">Действие</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {filteredItems.map((item) => {
              const cfg = ACTION_CONFIG[item.action as keyof typeof ACTION_CONFIG];
              const lengthsText =
                item.lengths_mm && item.lengths_mm.length > 0
                  ? item.lengths_mm.join(", ")
                  : item.length_mm
                    ? `${item.length_mm}`
                    : null;
              const quantitiesText =
                item.quantities_per_hanger && item.quantities_per_hanger.length > 0
                  ? item.quantities_per_hanger.map((q) => q ?? "—").join(", ")
                  : item.quantity_per_hanger ?? null;
              return (
                <tr key={item.sku} className="hover:bg-muted/50">
                  <td className="px-4 py-2 font-medium">{item.sku}</td>
                  <td className="px-4 py-2">{lengthsText ?? "—"}</td>
                  <td className="px-4 py-2">{quantitiesText ?? "—"}</td>
                  <td className="px-4 py-2">
                    {item.has_photo ? (
                      <span className="text-green-600 flex items-center gap-1">
                        <Image className="h-3.5 w-3.5" /> Есть
                      </span>
                    ) : (
                      <span className="text-muted-foreground">Нет</span>
                    )}
                  </td>
                  <td className="px-4 py-2">
                    {cfg && (
                      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${cfg.color}`}>
                        {cfg.icon} {cfg.label}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {filteredItems.length === 0 && (
          <div className="text-muted-foreground py-8 text-center">Нет записей</div>
        )}
      </div>
    </>
  );
}
