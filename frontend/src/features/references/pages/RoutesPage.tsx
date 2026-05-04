import { useCallback, useRef, useState } from "react";
import { Plus, Download } from "lucide-react";
import * as API from "@/shared/api/routes";
import { Button } from "@/shared/ui/Button";
import { toast } from "@/shared/ui/use-toast";
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogCancel, AlertDialogAction } from "@/shared/ui/AlertDialog";
import { RouteFlowBuilder } from "../components/RouteFlowBuilder";
import { RouteTreeOverview, type RouteTreeOverviewRef } from "../components/RouteTreeOverview";

export function RoutesPage() {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editRoute, setEditRoute] = useState<API.RouteDetail | null>(null);
  const [seedDialogOpen, setSeedDialogOpen] = useState(false);
  const [seeding, setSeeding] = useState(false);
  const treeRef = useRef<RouteTreeOverviewRef>(null);

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
      toast({ variant: "destructive", title: "Ошибка", description: e instanceof Error ? e.message : "Не удалось загрузить маршрут" });
    }
  };

  const handleSaved = () => {
    setDialogOpen(false);
    treeRef.current?.reload();
  };

  const handleSeed = async () => {
    setSeeding(true);
    try {
      await API.seedRoutes();
      toast({ title: "Маршрут загружен", description: "Создан маршрут со всеми участками", variant: "success" });
      treeRef.current?.reload();
    } catch (e) {
      toast({ variant: "destructive", title: "Ошибка", description: e instanceof Error ? e.message : "Не удалось загрузить маршрут" });
    } finally {
      setSeeding(false);
      setSeedDialogOpen(false);
    }
  };

  return (
    <section className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Маршруты обработки</h2>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" onClick={() => setSeedDialogOpen(true)}>
            <Download className="h-4 w-4 mr-1" />
            Загрузить маршрут
          </Button>
          <Button size="sm" onClick={handleCreate}><Plus className="h-4 w-4 mr-1" />Создать маршрут</Button>
        </div>
      </div>

      {/* Route Tree Overview */}
      <RouteTreeOverview ref={treeRef} onEditRoute={handleEdit} />

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
            <AlertDialogTitle>Загрузить стандартный маршрут?</AlertDialogTitle>
            <AlertDialogDescription>
              Будет создан маршрут включающий все участки по порядку. Существующие шаги будут заменены.
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
