import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { previewProductionPlan } from "@/shared/api/productionPlans";

type PreviewPosition = {
  id: number;
  source_sku: string;
  source_name: string | null;
  quantity: string;
  status: string;
  validation_status: string;
  validation_errors: string[] | null;
};

const statusLabels: Record<string, string> = {
  draft: "Черновик",
  invalid: "Ошибка",
  valid: "Валиден",
  approved: "Утвержден",
  released: "Запущен",
  cancelled: "Отменен",
};

export function PlanPreviewPage() {
  const { planId } = useParams<{ planId: string }>();
  const numericPlanId = Number(planId);

  const { data, isLoading, error } = useQuery({
    queryKey: ["plan-preview-page", numericPlanId],
    queryFn: () => previewProductionPlan(numericPlanId),
    enabled: Number.isFinite(numericPlanId) && numericPlanId > 0,
  });

  const rows = ((data?.positions as PreviewPosition[] | undefined) || []);

  if (!planId || !Number.isFinite(numericPlanId) || numericPlanId <= 0) {
    return <div className="p-6 text-sm text-red-600">Некорректный ID плана</div>;
  }

  if (isLoading) {
    return <div className="p-6 text-sm text-muted-foreground">Загрузка превью плана...</div>;
  }

  if (error) {
    return <div className="p-6 text-sm text-red-600">Ошибка загрузки: {String(error)}</div>;
  }

  return (
    <section className="space-y-4">
      <header className="page-header">
        <div>
          <h1 className="page-title">Превью плана</h1>
          <p className="page-subtitle">
            План #{Number((data as Record<string, unknown> | undefined)?.production_plan_id || 0)} · {String((data as Record<string, unknown> | undefined)?.plan_no || "—")}
          </p>
        </div>
        <Link to="/production-planning" className="text-sm text-blue-700 hover:underline">
          Назад к выполнению
        </Link>
      </header>

      <div className="flex gap-3 text-sm">
        <span className="px-3 py-1 rounded-full bg-muted">Статус: {String((data as Record<string, unknown> | undefined)?.status || "—")}</span>
        <span className="px-3 py-1 rounded-full bg-blue-100 text-blue-700">Позиции: {Number((data as Record<string, unknown> | undefined)?.positions_total || 0)}</span>
      </div>

      <div className="rounded-lg border overflow-auto">
        <table className="w-full text-sm">
          <thead className="border-b bg-muted/50">
            <tr>
              <th className="text-left p-2">ID</th>
              <th className="text-left p-2">Артикул</th>
              <th className="text-left p-2">Наименование</th>
              <th className="text-left p-2">Кол-во</th>
              <th className="text-left p-2">Статус</th>
              <th className="text-left p-2">Валидация</th>
              <th className="text-left p-2">Ошибки</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className="border-b">
                <td className="p-2">#{row.id}</td>
                <td className="p-2 font-mono">{row.source_sku}</td>
                <td className="p-2">{row.source_name || "—"}</td>
                <td className="p-2">{row.quantity}</td>
                <td className="p-2">{statusLabels[row.status] || row.status}</td>
                <td className="p-2">{row.validation_status}</td>
                <td className="p-2 text-xs text-red-600">{(row.validation_errors || []).join(", ") || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && <p className="p-4 text-sm text-muted-foreground text-center">В плане нет позиций</p>}
      </div>
    </section>
  );
}
