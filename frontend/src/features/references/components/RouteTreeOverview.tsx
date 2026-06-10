import { useEffect, useState, useCallback, forwardRef, useImperativeHandle } from "react";
import * as API from "@/shared/api/routes";
import type { Section } from "@/shared/api/sections";
import { Badge } from "@/shared/ui/Badge";
import { Input } from "@/shared/ui/Input";
import { Card, CardContent } from "@/shared/ui/Card";
import { apiClient } from "@/shared/api/client";
import { getErrorMessage } from "@/shared/api/client";
import { renderIcon } from "@/shared/ui/EntityDialog";
import { ArrowUp, ArrowDown, GripVertical } from "lucide-react";
import { toast } from "@/shared/ui/use-toast";

interface RouteTreeOverviewProps {
  onEditRoute: (route: API.RouteDetail) => void;
  readOnly?: boolean;
}

export interface RouteTreeOverviewRef {
  reload: () => void;
}

export const RouteTreeOverview = forwardRef<RouteTreeOverviewRef, RouteTreeOverviewProps>(function RouteTreeOverview({ onEditRoute, readOnly = false }: RouteTreeOverviewProps, ref) {
  const [routes, setRoutes] = useState<API.RouteDetail[]>([]);
  const [sections, setSections] = useState<Section[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [draggedIndex, setDraggedIndex] = useState<number | null>(null);

  const moveRoute = useCallback((fromIndex: number, toIndex: number) => {
    setRoutes((prev) => {
      if (toIndex < 0 || toIndex >= prev.length) return prev;
      const next = [...prev];
      const [moved] = next.splice(fromIndex, 1);
      next.splice(toIndex, 0, moved);
      return next;
    });
  }, []);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [routesList, sectionsList] = await Promise.all([
        apiClient.get<API.ProductionRoute[]>("/routes"),
        apiClient.get<Section[]>("/sections"),
      ]);

      setSections(sectionsList.data);

      const details: API.RouteDetail[] = [];

      for (const route of routesList.data) {
        const detail = await API.getRoute(route.id);
        details.push(detail);
      }

      setRoutes(details);
    } catch (e) {
      console.error("Failed to load route trees:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  const commitRouteReorder = useCallback(async () => {
    try {
      const ids = routes.map((r) => r.id).filter(Boolean);
      if (ids.length > 0) {
        await API.reorderRoutes(ids);
      }
    } catch (e) {
      toast({ title: "Ошибка сортировки", description: getErrorMessage(e), variant: "destructive" });
      await loadData();
    }
  }, [routes, loadData]);

  const moveRouteUp = useCallback((index: number) => {
    moveRoute(index, index - 1);
    setTimeout(() => commitRouteReorder(), 0);
  }, [moveRoute, commitRouteReorder]);

  const moveRouteDown = useCallback((index: number) => {
    moveRoute(index, index + 1);
    setTimeout(() => commitRouteReorder(), 0);
  }, [moveRoute, commitRouteReorder]);

  const handleDragStart = useCallback((index: number) => {
    setDraggedIndex(index);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent, index: number) => {
    e.preventDefault();
    if (draggedIndex === null || draggedIndex === index) return;
    moveRoute(draggedIndex, index);
    setDraggedIndex(index);
  }, [draggedIndex, moveRoute]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDraggedIndex(null);
    void commitRouteReorder();
  }, [commitRouteReorder]);

  const handleDragEnd = useCallback(() => {
    setDraggedIndex(null);
  }, []);

  useImperativeHandle(ref, () => ({ reload: loadData }));

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const getSectionById = (sectionId: number) => {
    return sections.find((s) => s.id === sectionId);
  };

  const filteredRoutes = routes.filter((r) =>
    r.name.toLowerCase().includes(search.toLowerCase()) ||
    (r.description || "").toLowerCase().includes(search.toLowerCase())
  );

  if (loading) {
    return <div className="text-muted-foreground py-4 text-center">Загрузка...</div>;
  }

  if (routes.length === 0) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-muted-foreground">
          <p>Нет маршрутов для отображения</p>
          <p className="text-sm">Создайте первый маршрут, чтобы увидеть дерево</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      <div className="relative max-w-sm">
        <Input placeholder="Поиск по названию..." value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>

      <div className="grid gap-3">
        {filteredRoutes.map((route, routeIndex) => {
          const hasParallelSteps = route.steps.some((s) => s.allow_parallel);
          const hasFinalStep = route.steps.some((s) => s.is_final);
          const isActive = route.is_active;

          return (
            <Card
              key={route.id}
              className="overflow-hidden transition-opacity"
              draggable={!readOnly}
              onDragStart={readOnly ? undefined : (e) => {
                (e.currentTarget as HTMLDivElement).style.opacity = "0.4";
                handleDragStart(routeIndex);
              }}
              onDragOver={readOnly ? undefined : (e) => handleDragOver(e, routeIndex)}
              onDrop={readOnly ? undefined : (e) => {
                (e.currentTarget as HTMLDivElement).style.opacity = "1";
                handleDrop(e);
              }}
              onDragEnd={readOnly ? undefined : (e) => {
                (e.currentTarget as HTMLDivElement).style.opacity = "1";
                handleDragEnd();
              }}
            >
              {/* Row - click to edit */}
              <div
                className="w-full flex items-center p-3 gap-3 cursor-pointer hover:bg-muted/50 transition-colors"
                onClick={() => onEditRoute(route)}
              >
                {/* Reorder controls */}
                {!readOnly && (
                  <div className="flex items-center gap-0.5 shrink-0" onClick={(e) => e.stopPropagation()}>
                    <span className="cursor-grab active:cursor-grabbing text-muted-foreground hover:text-foreground">
                      <GripVertical className="h-4 w-4" />
                    </span>
                    <button
                      type="button"
                      className="p-0.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:cursor-default cursor-pointer"
                      disabled={routeIndex === 0}
                      onClick={() => moveRouteUp(routeIndex)}
                      title="Переместить вверх"
                    >
                      <ArrowUp className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      className="p-0.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:cursor-default cursor-pointer"
                      disabled={routeIndex === filteredRoutes.length - 1}
                      onClick={() => moveRouteDown(routeIndex)}
                      title="Переместить вниз"
                    >
                      <ArrowDown className="h-3.5 w-3.5" />
                    </button>
                  </div>
                )}
                <div className="min-w-0 max-w-[360px]">
                  <div className="font-medium">{route.name}</div>
                  {route.description && (
                    <div className="text-xs text-muted-foreground truncate">
                      {route.description}
                    </div>
                  )}
                </div>

                {/* Step icons */}
                <div className="flex items-center gap-1.5 min-w-0 overflow-hidden">
                  {route.steps.map((step, index) => {
                    const section = getSectionById(step.section_id);
                    return (
                      <div key={step.id} className="relative group/step shrink-0">
                        <div
                          className={`flex h-8 w-8 items-center justify-center rounded-md border transition-all ${
                            step.is_final
                              ? "border-green-500 bg-green-50"
                              : step.allow_parallel
                              ? "border-blue-400 bg-blue-50"
                              : "border-border bg-card"
                          }`}
                        >
                          {section?.icon && section?.icon_color ? (
                            <span style={{ color: section.icon_color }}>
                              {renderIcon(section.icon, "h-4 w-4")}
                            </span>
                          ) : (
                            <span className="text-[10px] font-bold text-muted-foreground">{index + 1}</span>
                          )}
                        </div>
                        {/* Tooltip on hover */}
                        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover/step:block z-10">
                          <div className="bg-popover text-popover-foreground text-xs rounded-md px-2 py-1 shadow-md border whitespace-nowrap">
                            {section?.code}: {section?.name || step.operation_name}
                            {step.operation_code && ` (${step.operation_code})`}
                          </div>
                        </div>
                        {/* Connector */}
                        {index < route.steps.length - 1 && (
                          <div
                            className={`absolute -right-1.5 top-1/2 -translate-y-1/2 w-1.5 h-0.5 ${
                              step.allow_parallel ? "bg-blue-400" : "bg-muted-foreground/40"
                            }`}
                          />
                        )}
                      </div>
                    );
                  })}
                </div>

                {/* Badges */}
                <div className="flex gap-1 shrink-0">
                  {!isActive && (
                    <Badge variant="secondary" className="text-[10px]">
                      Неактивен
                    </Badge>
                  )}
                  {hasParallelSteps && (
                    <Badge variant="outline" className="text-[10px] bg-blue-50 text-blue-700 border-blue-200">
                      Ветвление
                    </Badge>
                  )}
                  {hasFinalStep && (
                    <Badge variant="outline" className="text-[10px] bg-green-50 text-green-700 border-green-200">
                      Финал
                    </Badge>
                  )}
                  <Badge variant="secondary" className="text-[10px]">
                    {route.steps.length} этапов
                  </Badge>
                </div>
              </div>
            </Card>
          );
        })}
      </div>

      {filteredRoutes.length === 0 && search && (
        <div className="text-muted-foreground py-8 text-center">Ничего не найдено по запросу "{search}"</div>
      )}
    </div>
  );
});
