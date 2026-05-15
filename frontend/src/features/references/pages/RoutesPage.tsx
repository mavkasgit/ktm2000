import { useCallback, useRef, useState } from "react";
import { Plus, Download } from "lucide-react";
import * as API from "@/shared/api/routes";
import { getErrorMessage } from "@/shared/api/client";
import { Button } from "@/shared/ui/Button";
import { toast } from "@/shared/ui/use-toast";
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogCancel, AlertDialogAction } from "@/shared/ui/AlertDialog";
import { RouteFlowBuilder } from "../components/RouteFlowBuilder";
import { RouteSelectionRulesSection } from "../components/RouteSelectionRulesSection";
import { RouteTreeOverview, type RouteTreeOverviewRef } from "../components/RouteTreeOverview";
import { ImportTemplatesPage } from "./ImportTemplatesPage";

type TabKey = "routes" | "templates";

export function RoutesPage() {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editRoute, setEditRoute] = useState<API.RouteDetail | null>(null);
  const [seedDialogOpen, setSeedDialogOpen] = useState(false);
  const [seeding, setSeeding] = useState(false);
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

  const handleSeed = async () => {
    setSeeding(true);
    try {
      const seeded = await API.seedRoutes();
      const rules = await API.listRouteSelectionRules();
      toast({
        title: "Маршруты загружены",
        description: `Создано/обновлено маршрутов: ${seeded.length}; восстановлено правил выбора: ${rules.length}`,
        variant: "success",
      });
      treeRef.current?.reload();
      setSeedRevision((value) => value + 1);
    } catch (e) {
      toast({ variant: "destructive", title: "Ошибка загрузки маршрутов", description: getErrorMessage(e) });
    } finally {
      setSeeding(false);
      setSeedDialogOpen(false);
    }
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
          <div className={showTemplates ? "flex-1" : "flex-1"}>
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Button size="sm" variant="outline" onClick={() => setSeedDialogOpen(true)}>
                  <Download className="h-4 w-4 mr-1" />
                  Загрузить маршрут
                </Button>
                <Button size="sm" onClick={handleCreate}><Plus className="h-4 w-4 mr-1" />Создать маршрут</Button>
              </div>
            </div>
            <RouteTreeOverview ref={treeRef} onEditRoute={handleEdit} />
          </div>
        )}

        {showTemplates && (
          <div className={showRoutes ? "flex-1 space-y-4" : "flex-1 space-y-4"}>
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
      />

      {/* Seed Confirmation */}
      <AlertDialog open={seedDialogOpen} onOpenChange={setSeedDialogOpen}>
        <AlertDialogContent className="max-w-sm">
          <AlertDialogHeader>
            <AlertDialogTitle>Загрузить типовые маршруты?</AlertDialogTitle>
            <AlertDialogDescription>
              Будут созданы/обновлены 12 характеристических маршрутов и глобальные правила выбора маршрута.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter className="flex-col-reverse sm:flex-row gap-2">
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction onClick={handleSeed} disabled={seeding}>
              {seeding ? "Загрузка..." : "Загрузить"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}
