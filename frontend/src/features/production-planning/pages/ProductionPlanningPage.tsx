import { useQuery } from "@tanstack/react-query";
import { getProductionPlanningOverview, type PlanningSectionOut, type PlanningPositionOut } from "@/shared/api/productionPlans";

const kindLabels: Record<string, string> = {
  production: "Производство",
  raw_stock: "Сырьевой склад",
  wip_stock: "Склад НЗП",
  finished_stock: "Склад готовой продукции",
};

const statusColors: Record<string, string> = {
  waiting: "bg-gray-200 text-gray-700",
  ready: "bg-blue-100 text-blue-700",
  in_progress: "bg-yellow-100 text-yellow-700",
  completed: "bg-green-100 text-green-700",
  waiting_previous: "bg-gray-200 text-gray-700",
  cancelled: "bg-red-100 text-red-700",
};

const statusLabels: Record<string, string> = {
  waiting: "Ожидает",
  ready: "Готово",
  in_progress: "В работе",
  completed: "Завершено",
  waiting_previous: "Ждёт предыдущий",
  cancelled: "Отменено",
};

function ProgressBar({ percent }: { percent: number }) {
  return (
    <div className="w-full bg-muted rounded-full h-2">
      <div
        className="h-2 rounded-full bg-primary transition-all"
        style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
      />
    </div>
  );
}

function PositionRow({ pos }: { pos: PlanningPositionOut }) {
  const hasActiveTask = pos.work_tasks.some((wt) => wt.status === "ready" || wt.status === "in_progress");
  const isComplete = pos.progress.completed_steps === pos.progress.total_steps;

  return (
    <div className={`border rounded-lg p-3 mb-2 ${isComplete ? "bg-green-50/50" : hasActiveTask ? "bg-yellow-50/50" : "bg-background"}`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Строка #{pos.source_row_number ?? "?"}</span>
          <span className="font-mono text-sm font-semibold">{pos.source_sku}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">{pos.route_name ?? "Без маршрута"}</span>
          <span className={`text-xs px-2 py-0.5 rounded-full ${isComplete ? "bg-green-200 text-green-800" : "bg-blue-100 text-blue-800"}`}>
            {pos.progress.completed_steps}/{pos.progress.total_steps}
          </span>
        </div>
      </div>
      <div className="mb-2">
        <ProgressBar percent={pos.progress.percent} />
      </div>
      <div className="text-xs text-muted-foreground mb-1">{pos.source_name ?? "—"}</div>
      <div className="flex gap-1 flex-wrap">
        {pos.work_tasks.map((wt) => (
          <span
            key={wt.id}
            className={`text-xs px-2 py-0.5 rounded-full ${statusColors[wt.status] ?? "bg-gray-100 text-gray-700"}`}
            title={`${wt.operation_name ?? wt.operation_code ?? "?"} — ${statusLabels[wt.status] ?? wt.status}`}
          >
            {wt.operation_code ?? "?"} {statusLabels[wt.status] ?? wt.status}
          </span>
        ))}
      </div>
    </div>
  );
}

function SectionCard({ section }: { section: PlanningSectionOut }) {
  return (
    <div className="border rounded-xl p-4 bg-card">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-lg font-semibold">{section.section_name}</h3>
          <p className="text-sm text-muted-foreground">
            {kindLabels[section.section_kind] ?? section.section_kind} · {section.section_code}
          </p>
        </div>
        <div className="flex gap-2 text-xs">
          <span className="px-2 py-1 rounded-full bg-gray-100 text-gray-700">Очередь: {section.ready_count}</span>
          <span className="px-2 py-1 rounded-full bg-yellow-100 text-yellow-700">В работе: {section.in_progress_count}</span>
          <span className="px-2 py-1 rounded-full bg-green-100 text-green-700">Завершено: {section.completed_count}</span>
        </div>
      </div>
      {section.positions.length === 0 ? (
        <p className="text-sm text-muted-foreground py-4 text-center">Нет позиций</p>
      ) : (
        section.positions.map((pos) => <PositionRow key={pos.plan_position_id} pos={pos} />)
      )}
    </div>
  );
}

export function ProductionPlanningPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["production-planning-overview"],
    queryFn: getProductionPlanningOverview,
  });

  if (isLoading) {
    return <div className="p-6 text-sm text-muted-foreground">Загрузка...</div>;
  }

  if (error) {
    return <div className="p-6 text-sm text-red-600">Ошибка загрузки: {String(error)}</div>;
  }

  if (!data || data.sections.length === 0) {
    return (
      <>
        <header className="page-header">
          <div>
            <h1 className="page-title">Выполнение</h1>
            <p className="page-subtitle">Нет утверждённых позиций с маршрутами</p>
          </div>
        </header>
      </>
    );
  }

  const totalPositions = data.sections.reduce((sum, s) => sum + s.positions_count, 0);
  const totalReady = data.sections.reduce((sum, s) => sum + s.ready_count, 0);
  const totalInProgress = data.sections.reduce((sum, s) => sum + s.in_progress_count, 0);
  const totalCompleted = data.sections.reduce((sum, s) => sum + s.completed_count, 0);

  return (
    <>
      <header className="page-header">
        <div>
          <h1 className="page-title">Выполнение</h1>
          <div className="flex gap-3 text-sm">
            <span className="px-3 py-1 rounded-full bg-muted">Всего: {totalPositions}</span>
            <span className="px-3 py-1 rounded-full bg-gray-100 text-gray-700">Очередь: {totalReady}</span>
            <span className="px-3 py-1 rounded-full bg-yellow-100 text-yellow-700">В работе: {totalInProgress}</span>
            <span className="px-3 py-1 rounded-full bg-green-100 text-green-700">Завершено: {totalCompleted}</span>
          </div>
        </div>
      </header>
      <div className="space-y-4">
        {data.sections.map((section) => (
          <SectionCard key={section.section_id} section={section} />
        ))}
      </div>
    </>
  );
}
