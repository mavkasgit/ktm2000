import { useEffect, useState, useCallback, forwardRef, useImperativeHandle } from "react";
import * as API from "@/shared/api/routes";
import type { Section } from "@/shared/api/sections";
import { Badge } from "@/shared/ui/Badge";
import { Input } from "@/shared/ui/Input";
import { Card, CardContent } from "@/shared/ui/Card";
import { apiClient } from "@/shared/api/client";
import { renderIcon } from "@/shared/ui/EntityDialog";

interface RouteTreeOverviewProps {
  onEditRoute: (route: API.RouteDetail) => void;
}

export interface RouteTreeOverviewRef {
  reload: () => void;
}

export const RouteTreeOverview = forwardRef<RouteTreeOverviewRef, RouteTreeOverviewProps>(function RouteTreeOverview({ onEditRoute }: RouteTreeOverviewProps, ref) {
  const [routes, setRoutes] = useState<API.RouteDetail[]>([]);
  const [sections, setSections] = useState<Section[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");

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
        {filteredRoutes.map((route) => {
          const hasParallelSteps = route.steps.some((s) => s.allow_parallel);
          const hasFinalStep = route.steps.some((s) => s.is_final);
          const isActive = route.is_active;

          return (
            <Card key={route.id} className="overflow-hidden">
              {/* Row - click to edit */}
              <div
                className="w-full flex items-center p-3 gap-3 cursor-pointer hover:bg-muted/50 transition-colors"
                onClick={() => onEditRoute(route)}
              >
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
