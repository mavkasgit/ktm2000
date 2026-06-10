import { useCallback, useRef, useState } from "react";
import { Plus } from "lucide-react";
import * as API from "@/shared/api/routes";
import { getErrorMessage } from "@/shared/api/client";
import { Button } from "@/shared/ui/Button";
import { toast } from "@/shared/ui/use-toast";
import { RouteFlowBuilder } from "../components/RouteFlowBuilder";
import { RouteSelectionRulesSection } from "../components/RouteSelectionRulesSection";
import { RouteTreeOverview, type RouteTreeOverviewRef } from "../components/RouteTreeOverview";
import { ImportTemplatesPage } from "./ImportTemplatesPage";
import { usePermission } from "@/features/auth/hooks/usePermission";

type TabKey = "routes" | "templates";

export function RoutesPage() {
  const { canEditReferences } = usePermission();
  const isReadOnly = !canEditReferences;
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editRoute, setEditRoute] = useState<API.RouteDetail | null>(null);
  const [seedRevision, setSeedRevision] = useState(0);
  const treeRef = useRef<RouteTreeOverviewRef>(null);
  const [activeTabs, setActiveTabs] = useState<Set<TabKey>>(new Set(["routes", "templates"]));

  const toggleTab = (tab: TabKey) => {
    setActiveTabs((prev) => {
      const next = new Set(prev);
      if (next.has(tab)) {
        if (next.size > 1) next.delete(tab);
      } else {
        next.add(tab);
      }
      return next;
    });
  };

  const handleCreate = useCallback(() => {
    setEditRoute(null);
    setDialogOpen(true);
  }, []);

  const handleEdit = async (route: API.ProductionRoute) => {
    try {
      const detail = await API.getRoute(route.id);
      setEditRoute(detail);
      setDialogOpen(true);
    } catch (e) {
      toast({ variant: "destructive", title: `Ошибка загрузки маршрута #${route.id}`, description: getErrorMessage(e) });
    }
  };

  const handleSaved = () => {
    setDialogOpen(false);
    treeRef.current?.reload();
  };

  const showRoutes = activeTabs.has("routes");
  const showTemplates = activeTabs.has("templates");

  return (
    <section className="space-y-4">
      {/* Tab bar */}
      <div className="flex gap-4">
        <div className="flex-1">
          <Button
            variant={showRoutes ? "default" : "outline"}
            className={`w-full ${showRoutes ? "bg-black/10 hover:bg-black/20 text-black text-lg" : ""}`}
            onClick={() => toggleTab("routes")}
          >
            Маршруты обработки
          </Button>
        </div>
        <div className="flex-1">
          <Button
            variant={showTemplates ? "default" : "outline"}
            className={`w-full ${showTemplates ? "bg-black/10 hover:bg-black/20 text-black text-lg" : ""}`}
            onClick={() => toggleTab("templates")}
          >
            Шаблоны и правила
          </Button>
        </div>
      </div>

      {/* Content */}
      <div className="flex gap-4 items-start">
        {showRoutes && (
          <div className="flex-1">
            {!isReadOnly && (
              <div className="flex items-center justify-between mb-4">
                <Button size="sm" onClick={handleCreate}><Plus className="h-4 w-4 mr-1" />Создать маршрут</Button>
              </div>
            )}
            <RouteTreeOverview ref={treeRef} onEditRoute={handleEdit} readOnly={isReadOnly} />
          </div>
        )}

        {showTemplates && (
          <div className="flex-1 space-y-4">
            <div className="rounded-lg border p-4">
              <ImportTemplatesPage />
            </div>
            <RouteSelectionRulesSection refreshKey={seedRevision} />
          </div>
        )}
      </div>

      {/* Flow Builder Dialog */}
      <RouteFlowBuilder
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        route={editRoute}
        onSave={handleSaved}
        readOnly={isReadOnly}
      />
    </section>
  );
}
