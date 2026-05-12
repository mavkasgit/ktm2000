import { useMemo, useState, useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getProductionPlanningRowDetail,
  listPlans,
  listProductionPlanningRows,
  takeToWork,
  cancelPositionExecution,
  type ProductionPlanningRow,
  type TakeToWorkResult,
} from "@/shared/api/productionPlans";
import { listSections } from "@/shared/api/sections";
import { Badge, Button, Checkbox, Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, Input, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, renderIcon } from "@/shared/ui";
import { toast } from "@/shared/ui/use-toast";
import { getErrorMessage } from "@/shared/api/client";

const positionStatusLabels: Record<string, string> = {
  draft: "Черновик",
  invalid: "Ошибка",
  valid: "Валиден",
  approved: "Утвержден",
  released: "Запущен",
  cancelled: "Отменен",
};

const positionStatusColor: Record<string, string> = {
  draft: "bg-gray-100 text-gray-700",
  invalid: "bg-red-100 text-red-700",
  valid: "bg-green-100 text-green-700",
  approved: "bg-blue-100 text-blue-700",
  released: "bg-emerald-100 text-emerald-700",
  cancelled: "bg-red-100 text-red-700",
};

const routeSourceLabels: Record<string, string> = {
  manual: "ручной",
  auto: "авто",
  missing: "не найден",
};

function fmtQty(value: number): string {
  if (Number.isInteger(value)) {
    return String(value);
  }
  return value.toFixed(3).replace(/\.?0+$/, "");
}

function planPreviewUrl(planId: number): string {
  return `/plans/${planId}/preview`;
}

function calcExecutionPercent(fact: number, plan: number): number {
  if (!Number.isFinite(plan) || plan <= 0) {
    return 0;
  }
  return (fact / plan) * 100;
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full ${positionStatusColor[status] || "bg-gray-100 text-gray-700"}`}>
      {positionStatusLabels[status] || status}
    </span>
  );
}

function RowRouteCell({ row }: { row: ProductionPlanningRow }) {
  if (row.route_name) {
    return (
      <span className="text-xs text-blue-700">
        {row.route_name}
        <span className="text-muted-foreground"> ({routeSourceLabels[row.route_source || ""] || row.route_source || "—"})</span>
      </span>
    );
  }
  return <span className="text-xs text-red-600">{row.route_error || "Не назначен"}</span>;
}

export function ExecutionPage() {
  const [selectedPositionId, setSelectedPositionId] = useState<number | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [skuFilter, setSkuFilter] = useState("");
  const [rowFilter, setRowFilter] = useState("");
  const [planFilter, setPlanFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");

  const { data: rows, isLoading, error } = useQuery({
    queryKey: ["production-planning-rows"],
    queryFn: listProductionPlanningRows,
  });
  const { data: plans } = useQuery({
    queryKey: ["plans"],
    queryFn: listPlans,
  });
  const { data: sections } = useQuery({
    queryKey: ["sections"],
    queryFn: listSections,
  });

  const { data: detail, isLoading: detailLoading, error: detailError } = useQuery({
    queryKey: ["production-planning-row-detail", selectedPositionId],
    queryFn: () => getProductionPlanningRowDetail(selectedPositionId as number),
    enabled: drawerOpen && selectedPositionId !== null,
  });

  const planNameById = useMemo(() => {
    const map = new Map<number, string>();
    (plans || []).forEach((p) => map.set(p.id, p.plan_no));
    return map;
  }, [plans]);
  const sectionMetaById = useMemo(() => {
    const map = new Map<number, { icon: string | null; icon_color: string | null }>();
    (sections || []).forEach((s) => map.set(s.id, { icon: s.icon, icon_color: s.icon_color }));
    return map;
  }, [sections]);

  const queryClient = useQueryClient();
  const [selectedRows, setSelectedRows] = useState<Set<number>>(new Set());
  const [launchDialog, setLaunchDialog] = useState<{ open: boolean; mode: "single" | "bulk"; positionIds: number[] }>({
    open: false,
    mode: "single",
    positionIds: [],
  });
  const [launchResults, setLaunchResults] = useState<TakeToWorkResult[]>([]);
  const [resultsDialogOpen, setResultsDialogOpen] = useState(false);

  const takeToWorkMutation = useMutation({
    mutationFn: takeToWork,
    onSuccess: (data) => {
      setLaunchResults(data.results);
      setResultsDialogOpen(true);
      const successCount = data.results.filter((r) => r.status === "success").length;
      const failCount = data.results.filter((r) => r.status === "failed").length;
      const alreadyCount = data.results.filter((r) => r.status === "already_started").length;
      if (failCount > 0) {
        toast({ title: "Частичный успех", description: `${successCount} успешно, ${failCount} ошибок, ${alreadyCount} уже запущено`, variant: "destructive" });
      } else {
        toast({ title: "Запуск завершён", description: `${successCount} запущено, ${alreadyCount} уже было запущено`, variant: "success" });
      }
      queryClient.invalidateQueries({ queryKey: ["production-planning-rows"] });
      setSelectedRows(new Set());
    },
    onError: (err) => toast({ title: "Ошибка запуска", description: getErrorMessage(err), variant: "destructive" }),
  });

  const [cancelDialog, setCancelDialog] = useState<{ open: boolean; positionId: number | null; isReleased: boolean }>({
    open: false,
    positionId: null,
    isReleased: false,
  });

  const cancelPositionMutation = useMutation({
    mutationFn: cancelPositionExecution,
    onSuccess: () => {
      toast({ title: "Позиция отменена", variant: "success" });
      queryClient.invalidateQueries({ queryKey: ["production-planning-rows"] });
    },
    onError: (err) => toast({ title: "Ошибка отмены", description: getErrorMessage(err), variant: "destructive" }),
  });

  const isRowLaunched = useCallback((row: ProductionPlanningRow) => {
    return row.has_tasks || row.is_released;
  }, []);

  const getLaunchBlockReason = useCallback((row: ProductionPlanningRow) => {
    if (row.has_tasks || row.is_released) return "Уже запущено";
    if (row.position_status !== "approved") return `Статус "${positionStatusLabels[row.position_status] || row.position_status}"`;
    if (!row.route_id) return row.route_error || "Нет маршрута";
    return null;
  }, []);

  const handleSingleLaunch = useCallback((row: ProductionPlanningRow) => {
    const reason = getLaunchBlockReason(row);
    if (reason) {
      toast({ title: "Невозможно запустить", description: reason, variant: "destructive" });
      return;
    }
    setLaunchDialog({ open: true, mode: "single", positionIds: [row.plan_position_id] });
  }, [getLaunchBlockReason]);

  const handleBulkLaunch = useCallback(() => {
    const ids = Array.from(selectedRows);
    if (ids.length === 0) {
      toast({ title: "Выберите строки", description: "Отметьте строки для запуска", variant: "destructive" });
      return;
    }
    setLaunchDialog({ open: true, mode: "bulk", positionIds: ids });
  }, [selectedRows]);

  const toggleRowSelection = useCallback((positionId: number, checked: boolean) => {
    setSelectedRows((prev) => {
      const next = new Set(prev);
      if (checked) next.add(positionId);
      else next.delete(positionId);
      return next;
    });
  }, []);

  const confirmLaunch = useCallback(() => {
    takeToWorkMutation.mutate(launchDialog.positionIds);
    setLaunchDialog({ open: false, mode: "single", positionIds: [] });
  }, [launchDialog.positionIds, takeToWorkMutation]);

  const handleCancel = useCallback((row: ProductionPlanningRow) => {
    setCancelDialog({ open: true, positionId: row.plan_position_id, isReleased: row.is_released });
  }, []);

  const confirmCancel = useCallback(() => {
    if (cancelDialog.positionId) {
      cancelPositionMutation.mutate(cancelDialog.positionId);
    }
    setCancelDialog({ open: false, positionId: null, isReleased: false });
  }, [cancelDialog.positionId, cancelPositionMutation]);

  const filteredRows = useMemo(() => {
    const list = rows || [];
    return list.filter((row) => {
      if (statusFilter !== "all" && row.position_status !== statusFilter) {
        return false;
      }
      if (skuFilter.trim()) {
        const skuTerm = skuFilter.trim().toLowerCase();
        if (!row.source_sku.toLowerCase().includes(skuTerm) && !(row.source_name || "").toLowerCase().includes(skuTerm)) {
          return false;
        }
      }
      if (rowFilter.trim()) {
        const rowTerm = rowFilter.trim();
        if (!String(row.source_row_number ?? "").includes(rowTerm)) {
          return false;
        }
      }
      if (planFilter.trim()) {
        const planTerm = planFilter.trim().toLowerCase();
        const planText = `${row.production_plan_id} ${planNameById.get(row.production_plan_id) || ""}`.toLowerCase();
        if (!planText.includes(planTerm)) {
          return false;
        }
      }
      return true;
    });
  }, [rows, statusFilter, skuFilter, rowFilter, planFilter, planNameById]);

  const totalRows = rows?.length || 0;
  const releasedRows = rows?.filter((r) => r.is_released).length || 0;
  const rowsWithTasks = rows?.filter((r) => r.has_tasks).length || 0;

  const openDetail = (positionId: number) => {
    setSelectedPositionId(positionId);
    setDrawerOpen(true);
  };

  if (isLoading) {
    return <div className="p-6 text-sm text-muted-foreground">Загрузка...</div>;
  }

  if (error) {
    return <div className="p-6 text-sm text-red-600">Ошибка загрузки: {String(error)}</div>;
  }

  return (
    <>
      <header className="page-header">
        <div>
          <h1 className="page-title">Контроль выполнения</h1>
          <div className="flex gap-3 text-sm">
            <span className="px-3 py-1 rounded-full bg-muted">Строк всего: {totalRows}</span>
            <span className="px-3 py-1 rounded-full bg-emerald-100 text-emerald-700">Запущено: {releasedRows}</span>
            <span className="px-3 py-1 rounded-full bg-blue-100 text-blue-700">С задачами: {rowsWithTasks}</span>
          </div>
        </div>
        {selectedRows.size > 0 && (
          <Button onClick={handleBulkLaunch} variant="default">
            <span className="ml-1">Взять выбранные в работу ({selectedRows.size})</span>
          </Button>
        )}
      </header>

      <section className="space-y-3">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
          <Input placeholder="Поиск по SKU / наименованию" value={skuFilter} onChange={(e) => setSkuFilter(e.target.value)} />
          <Input placeholder="Фильтр по номеру строки" value={rowFilter} onChange={(e) => setRowFilter(e.target.value)} />
          <Input placeholder="Фильтр по плану (ID или PLAN-...)" value={planFilter} onChange={(e) => setPlanFilter(e.target.value)} />
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger>
              <SelectValue placeholder="Статус" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Все статусы</SelectItem>
              <SelectItem value="approved">Утвержден</SelectItem>
              <SelectItem value="released">Запущен</SelectItem>
              <SelectItem value="cancelled">Отменен</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="rounded-lg border overflow-auto">
          <table className="w-full text-sm">
            <thead className="border-b bg-muted/50">
              <tr>
                <th className="text-left p-2 w-8"></th>
                <th className="text-left p-2">Строка</th>
                <th className="text-left p-2">План</th>
                <th className="text-left p-2">SKU</th>
                <th className="text-left p-2">Наименование</th>
                <th className="text-left p-2">Кол-во</th>
                <th className="text-left p-2">Маршрут</th>
                <th className="text-left p-2">Статус</th>
                <th className="text-left p-2">Задачи</th>
                <th className="text-left p-2">Действия</th>
              </tr>
            </thead>
            <tbody>
              {filteredRows.map((row) => {
                const canLaunch = row.position_status === "approved" && !row.has_tasks && !row.is_released && !!row.route_id;
                const blockReason = getLaunchBlockReason(row);
                return (
                <tr
                  key={row.plan_position_id}
                  className="border-b hover:bg-accent/30 cursor-pointer"
                  onClick={() => openDetail(row.plan_position_id)}
                >
                  <td className="p-2" onClick={(e) => e.stopPropagation()}>
                    {canLaunch && (
                      <Checkbox
                        checked={selectedRows.has(row.plan_position_id)}
                        onCheckedChange={(checked) => toggleRowSelection(row.plan_position_id, !!checked)}
                      />
                    )}
                  </td>
                  <td className="p-2">#{row.source_row_number ?? "—"}</td>
                  <td className="p-2">
                    {(() => {
                      const planName = planNameById.get(row.production_plan_id) || "—";
                      return (
                        <>
                          <div className="text-xs text-muted-foreground">{row.production_plan_id}</div>
                          {planName !== "—" ? (
                            <a
                              href={planPreviewUrl(row.production_plan_id)}
                              target="_blank"
                              rel="noreferrer"
                              title={planName}
                              className="text-blue-700 hover:underline inline-block max-w-[240px] truncate align-bottom"
                              onClick={(e) => e.stopPropagation()}
                            >
                              План
                            </a>
                          ) : (
                            <div>—</div>
                          )}
                        </>
                      );
                    })()}
                  </td>
                  <td className="p-2 font-mono">{row.source_sku}</td>
                  <td className="p-2">{row.source_name || "—"}</td>
                  <td className="p-2">{fmtQty(row.quantity)}</td>
                  <td className="p-2">
                    <RowRouteCell row={row} />
                  </td>
                  <td className="p-2">
                    <StatusBadge status={row.position_status} />
                  </td>
                  <td className="p-2">
                    <Badge variant={row.has_tasks ? "default" : "secondary"}>{row.has_tasks ? "Есть" : "Нет"}</Badge>
                  </td>
                  <td className="p-2" onClick={(e) => e.stopPropagation()}>
                    <div className="flex gap-1">
                      {canLaunch ? (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => handleSingleLaunch(row)}
                        >
                          Взять в работу
                        </Button>
                      ) : (
                        <span
                          className="text-xs text-muted-foreground"
                          title={blockReason || ""}
                        >
                          {blockReason || "—"}
                        </span>
                      )}
                      {row.position_status === "approved" && (
                        <Button
                          size="sm"
                          variant="ghost"
                          className="text-red-600 hover:text-red-700"
                          onClick={() => handleCancel(row)}
                        >
                          Отменить
                        </Button>
                      )}
                      {row.position_status === "released" && (
                        <Button
                          size="sm"
                          variant="ghost"
                          className="text-red-600 hover:text-red-700"
                          onClick={() => handleCancel(row)}
                        >
                          Остановить
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
          {filteredRows.length === 0 && <p className="p-4 text-sm text-muted-foreground text-center">Нет строк по выбранному фильтру</p>}
        </div>
      </section>

      <Dialog
        open={drawerOpen}
        onOpenChange={(open) => {
          setDrawerOpen(open);
          if (!open) {
            setSelectedPositionId(null);
          }
        }}
      >
        <DialogContent className="!left-auto !right-0 !top-0 !translate-x-0 !translate-y-0 h-screen max-h-screen w-[min(100vw,940px)] max-w-none rounded-none border-l p-0 flex flex-col gap-0">
          <div className="p-6 border-b">
            <DialogHeader>
              <DialogTitle>Детализация строки выполнения</DialogTitle>
              <DialogDescription>
                Маршрут, этапы и метрики план/факт/брак по выбранной строке импорта.
              </DialogDescription>
            </DialogHeader>
          </div>

          <div className="flex-1 overflow-auto p-6">
            {detailLoading && <p className="text-sm text-muted-foreground">Загрузка детализации...</p>}
            {detailError && <p className="text-sm text-red-600">Ошибка: {String(detailError)}</p>}
            {!detailLoading && !detailError && detail && (
              <div className="space-y-4">
                <div className="rounded-lg border p-4">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
                    <div>
                      <div className="text-muted-foreground">Строка импорта</div>
                      <div className="font-medium">#{detail.source_row_number ?? "—"}</div>
                    </div>
                    <div>
                      <div className="text-muted-foreground">План</div>
                      <div className="font-medium">
                        {detail.production_plan_id} ·{" "}
                        {(() => {
                          const planName = planNameById.get(detail.production_plan_id) || "—";
                          if (planName === "—") {
                            return "—";
                          }
                          return (
                            <a
                              href={planPreviewUrl(detail.production_plan_id)}
                              target="_blank"
                              rel="noreferrer"
                              title={planName}
                              className="text-blue-700 hover:underline inline-block max-w-[320px] truncate align-bottom"
                            >
                              План
                            </a>
                          );
                        })()}
                      </div>
                    </div>
                    <div>
                      <div className="text-muted-foreground">SKU</div>
                      <div className="font-mono font-medium">{detail.source_sku}</div>
                    </div>
                    <div>
                      <div className="text-muted-foreground">Количество</div>
                      <div className="font-medium">{fmtQty(detail.quantity)}</div>
                    </div>
                    <div>
                      <div className="text-muted-foreground">Статус позиции</div>
                      <div className="pt-1">
                        <StatusBadge status={detail.position_status} />
                      </div>
                    </div>
                    <div>
                      <div className="text-muted-foreground">Маршрут</div>
                      <div className="font-medium">
                        {detail.route_name || detail.route_error || "Не назначен"}
                        {detail.route_source && (
                          <span className="text-muted-foreground"> ({routeSourceLabels[detail.route_source] || detail.route_source})</span>
                        )}
                      </div>
                    </div>
                  </div>
                  {detail.not_started && (
                    <div className="mt-3">
                      <Badge variant="secondary">Не запущено: задачи по этапам еще не созданы</Badge>
                    </div>
                  )}
                </div>

                <div className="rounded-lg border overflow-auto">
                  <table className="w-full text-sm">
                    <thead className="border-b bg-muted/50">
                      <tr>
                        <th className="text-left p-2">Этап</th>
                        <th className="text-left p-2">Участок</th>
                        <th className="text-left p-2">План</th>
                        <th className="text-left p-2">Факт</th>
                        <th className="text-left p-2">Брак</th>
                        <th className="text-left p-2">% выполнения</th>
                      </tr>
                    </thead>
                    <tbody>
                      {detail.stages.map((stage) => (
                        <tr key={stage.route_step_id} className="border-b">
                          <td className="p-2">#{stage.sequence}</td>
                          <td className="p-2">
                            {(() => {
                              const meta = sectionMetaById.get(stage.section_id);
                              const color = meta?.icon_color || "#64748B";
                              return (
                                <div className="flex items-start gap-2">
                                  <span
                                    className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md"
                                    style={{ backgroundColor: `${color}20`, color }}
                                  >
                                    {meta?.icon ? renderIcon(meta.icon, "h-4 w-4") : <span className="h-2 w-2 rounded-full bg-current" />}
                                  </span>
                                  <div>
                                    <div className="font-medium">{stage.section_name}</div>
                                    <div className="text-xs text-muted-foreground">
                                      {stage.section_code} · {stage.operation_name}
                                    </div>
                                  </div>
                                </div>
                              );
                            })()}
                          </td>
                          <td className="p-2">{fmtQty(stage.planned_quantity)}</td>
                          <td className="p-2">{fmtQty(stage.completed_quantity)}</td>
                          <td className="p-2">{fmtQty(stage.rejected_quantity)}</td>
                          <td className="p-2">{calcExecutionPercent(stage.completed_quantity, stage.planned_quantity).toFixed(1)}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {detail.stages.length === 0 && (
                    <p className="p-4 text-sm text-muted-foreground text-center">Маршрутные этапы отсутствуют для этой строки</p>
                  )}
                </div>
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>

      <Dialog
        open={launchDialog.open}
        onOpenChange={(open) => {
          if (!open) setLaunchDialog({ open: false, mode: "single", positionIds: [] });
        }}
      >
        <DialogContent className="sm:max-w-[480px]">
          <DialogHeader>
            <DialogTitle>Взять в работу</DialogTitle>
            <DialogDescription>
              {launchDialog.mode === "single"
                ? "Будут созданы задачи по всем этапам маршрута для выбранной строки."
                : `Будут созданы задачи по всем этапам маршрута для ${launchDialog.positionIds.length} выбранных строк.`}
            </DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setLaunchDialog({ open: false, mode: "single", positionIds: [] })}>
              Отмена
            </Button>
            <Button onClick={confirmLaunch} disabled={takeToWorkMutation.isPending}>
              {takeToWorkMutation.isPending ? "Запуск..." : "Запустить"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog
        open={cancelDialog.open}
        onOpenChange={(open) => {
          if (!open) setCancelDialog({ open: false, positionId: null, isReleased: false });
        }}
      >
        <DialogContent className="sm:max-w-[480px]">
          <DialogHeader>
            <DialogTitle>{cancelDialog.isReleased ? "Остановить выполнение?" : "Отменить позицию?"}</DialogTitle>
            <DialogDescription>
              {cancelDialog.isReleased
                ? "Позиция уже запущена. Остановка выполнения переведёт её в статус «Отменен». Это действие нельзя отменить."
                : "Отмена переведёт позицию в статус «Отменен». Это действие нельзя отменить."}
            </DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setCancelDialog({ open: false, positionId: null, isReleased: false })}>
              Отмена
            </Button>
            <Button variant="destructive" onClick={confirmCancel} disabled={cancelPositionMutation.isPending}>
              {cancelPositionMutation.isPending ? "Отмена..." : cancelDialog.isReleased ? "Остановить" : "Отменить"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog
        open={resultsDialogOpen}
        onOpenChange={(open) => {
          if (!open) setResultsDialogOpen(false);
        }}
      >
        <DialogContent className="sm:max-w-[560px]">
          <DialogHeader>
            <DialogTitle>Результат запуска</DialogTitle>
            <DialogDescription>
              {launchResults.filter((r) => r.status === "success").length} успешно,{" "}
              {launchResults.filter((r) => r.status === "already_started").length} уже запущено,{" "}
              {launchResults.filter((r) => r.status === "failed").length} ошибок
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-[320px] overflow-auto space-y-2">
            {launchResults.map((result) => (
              <div key={result.position_id} className="rounded border p-2 text-sm">
                <div className="flex items-center justify-between">
                  <span className="font-medium">Позиция #{result.position_id}</span>
                  <Badge
                    variant={result.status === "success" ? "default" : result.status === "already_started" ? "secondary" : "destructive"}
                  >
                    {result.status === "success" ? "Успешно" : result.status === "already_started" ? "Уже запущено" : "Ошибка"}
                  </Badge>
                </div>
                {result.reason && <div className="text-xs text-muted-foreground mt-1">{result.reason}</div>}
                {result.tasks_created != null && (
                  <div className="text-xs text-muted-foreground mt-1">Задач создано: {result.tasks_created}</div>
                )}
              </div>
            ))}
          </div>
          <div className="flex justify-end pt-2">
            <Button onClick={() => setResultsDialogOpen(false)}>Закрыть</Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
