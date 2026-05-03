import { useCallback, useEffect, useState } from "react";
import { Plus, Pencil, Trash2, ArrowUp, ArrowDown, CheckCircle, AlertCircle, X } from "lucide-react";
import * as API from "@/shared/api/routes";
import { Button } from "@/shared/ui/Button";
import { Input } from "@/shared/ui/Input";
import { Badge } from "@/shared/ui/Badge";
import { Card, CardContent } from "@/shared/ui/Card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/shared/ui/Dialog";
import { toast } from "@/shared/ui/use-toast";
import { apiClient } from "@/shared/api/client";

const CONDITION_FIELDS = [
  { value: "profile_type", label: "Вид профиля" },
  { value: "alloy", label: "Сплав" },
  { value: "color", label: "Цвет" },
  { value: "anod_type", label: "Тип анодирования" },
  { value: "length_mm", label: "Длина, мм" },
  { value: "quantity_per_hanger", label: "Кол-во на подвесе" },
];

const OPERATORS = [
  { value: "=", label: "=" },
  { value: "!=", label: "!=" },
  { value: "in", label: "В списке" },
  { value: "contains", label: "Содержит" },
];

export function RoutesPage() {
  const [routes, setRoutes] = useState<API.ProductionRoute[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editRoute, setEditRoute] = useState<API.RouteDetail | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<API.ProductionRoute | null>(null);
  const [activeTab, setActiveTab] = useState<"info" | "steps" | "rules">("info");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await API.listRoutes(search || undefined);
      setRoutes(data);
    } catch (e) {
      toast({ variant: "destructive", title: "Ошибка", description: e instanceof Error ? e.message : "Не удалось загрузить маршруты" });
    } finally {
      setLoading(false);
    }
  }, [search]);

  useEffect(() => { void load(); }, [load]);

  const handleCreate = () => {
    setEditRoute(null);
    setActiveTab("info");
    setDialogOpen(true);
  };

  const handleEdit = async (route: API.ProductionRoute) => {
    try {
      const detail = await API.getRoute(route.id);
      setEditRoute(detail);
      setActiveTab("info");
      setDialogOpen(true);
    } catch (e) {
      toast({ variant: "destructive", title: "Ошибка", description: e instanceof Error ? e.message : "Не удалось загрузить маршрут" });
    }
  };

  const handleDelete = async () => {
    if (!deleteConfirm) return;
    try {
      await API.deleteRoute(deleteConfirm.id);
      toast({ variant: "success", title: "Удалено", description: `Маршрут "${deleteConfirm.name}" удалён` });
      setDeleteConfirm(null);
      await load();
    } catch (e) {
      toast({ variant: "destructive", title: "Ошибка", description: e instanceof Error ? e.message : "Не удалось удалить маршрут" });
    }
  };

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Маршруты обработки</h2>
        <Button size="sm" onClick={handleCreate}><Plus className="h-4 w-4 mr-1" />Создать маршрут</Button>
      </div>

      <div className="relative max-w-sm">
        <Input placeholder="Поиск по названию..." value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>

      {loading ? (
        <div className="text-muted-foreground py-8 text-center">Загрузка...</div>
      ) : routes.length === 0 ? (
        <div className="text-muted-foreground py-8 text-center">Нет маршрутов</div>
      ) : (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted">
              <tr>
                <th className="px-4 py-3 text-left font-medium">Название</th>
                <th className="px-4 py-3 text-left font-medium">Описание</th>
                <th className="px-4 py-3 text-left font-medium">Этапы</th>
                <th className="px-4 py-3 text-left font-medium">Правила</th>
                <th className="px-4 py-3 text-left font-medium">Статус</th>
                <th className="px-4 py-3 text-left font-medium w-20"></th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {routes.map((route) => (
                <tr key={route.id} className="hover:bg-muted/50">
                  <td className="px-4 py-2 font-medium">{route.name}</td>
                  <td className="px-4 py-2 text-muted-foreground max-w-[200px] truncate">{route.description || "—"}</td>
                  <td className="px-4 py-2"><RouteStepsBadge routeId={route.id} /></td>
                  <td className="px-4 py-2"><RouteRulesBadge routeId={route.id} /></td>
                  <td className="px-4 py-2">
                    <Badge variant={route.is_active ? "outline" : "secondary"} className={route.is_active ? "bg-green-50 text-green-700 border-green-200" : ""}>
                      {route.is_active ? "Активен" : "Неактивен"}
                    </Badge>
                  </td>
                  <td className="px-4 py-2">
                    <div className="flex gap-1">
                      <Button variant="ghost" size="sm" onClick={() => handleEdit(route)}><Pencil className="h-4 w-4" /></Button>
                      <Button variant="ghost" size="sm" onClick={() => setDeleteConfirm(route)}><Trash2 className="h-4 w-4 text-destructive" /></Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Edit/Create Dialog */}
      <RouteDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        route={editRoute}
        activeTab={activeTab}
        onTabChange={setActiveTab}
        onSave={load}
      />

      {/* Delete Confirmation */}
      <Dialog open={!!deleteConfirm} onOpenChange={() => setDeleteConfirm(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Удалить маршрут?</DialogTitle>
            <DialogDescription>
              {deleteConfirm && `Маршрут "${deleteConfirm.name}" будет удалён со всеми этапами и правилами.`}
            </DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setDeleteConfirm(null)}>Отмена</Button>
            <Button variant="destructive" onClick={handleDelete}>Удалить</Button>
          </div>
        </DialogContent>
      </Dialog>
    </section>
  );
}

function RouteStepsBadge({ routeId }: { routeId: number }) {
  const [count, setCount] = useState(0);
  useEffect(() => {
    API.getRoute(routeId).then((r) => setCount(r.steps.length)).catch(() => {});
  }, [routeId]);
  return count > 0 ? <Badge variant="secondary">{count} этапов</Badge> : <span className="text-muted-foreground">—</span>;
}

function RouteRulesBadge({ routeId }: { routeId: number }) {
  const [count, setCount] = useState(0);
  useEffect(() => {
    API.getRoute(routeId).then((r) => setCount(r.rules.length)).catch(() => {});
  }, [routeId]);
  return count > 0 ? <Badge variant="secondary">{count} правил</Badge> : <span className="text-muted-foreground">Дефолтный</span>;
}

// --- Route Dialog (Create/Edit with tabs) ---

function RouteDialog({
  open, onOpenChange, route, activeTab, onTabChange, onSave,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  route: API.RouteDetail | null;
  activeTab: string;
  onTabChange: (v: "info" | "steps" | "rules") => void;
  onSave: () => void;
}) {
  const [name, setName] = useState(route?.name ?? "");
  const [description, setDescription] = useState(route?.description ?? "");
  const [isActive, setIsActive] = useState(route?.is_active ?? true);
  const [steps, setSteps] = useState<API.StepInput[]>(route?.steps.map((s) => ({
    sequence: s.sequence, section_id: s.section_id, operation_code: s.operation_code,
    operation_name: s.operation_name, norm_time_minutes: s.norm_time_minutes, is_final: s.is_final,
  })) ?? []);
  const [rules, setRules] = useState<API.MatchingRule[]>(route?.rules ?? []);
  const [saving, setSaving] = useState(false);
  const [sections, setSections] = useState<{ id: number; code: string; name: string }[]>([]);

  useEffect(() => {
    apiClient.get("/sections").then((r) => setSections(r.data)).catch(() => {});
  }, []);

  const handleSave = async () => {
    if (!name.trim()) { toast({ variant: "destructive", title: "Ошибка", description: "Название обязательно" }); return; }
    setSaving(true);
    try {
      if (route) {
        await API.updateRoute(route.id, { name: name.trim(), description: description.trim() || null, is_active: isActive });
        await API.replaceSteps(route.id, steps);
        toast({ variant: "success", title: "Сохранено", description: "Маршрут обновлён" });
      } else {
        const created = await API.createRoute({ name: name.trim(), description: description.trim() || null, is_active: isActive });
        if (steps.length > 0) await API.replaceSteps(created.id, steps);
        toast({ variant: "success", title: "Создано", description: "Маршрут создан" });
      }
      onOpenChange(false);
      onSave();
    } catch (e) {
      toast({ variant: "destructive", title: "Ошибка", description: e instanceof Error ? e.message : "Ошибка сохранения" });
    } finally {
      setSaving(false);
    }
  };

  const addStep = () => {
    const maxSeq = steps.reduce((m, s) => Math.max(m, s.sequence), 0);
    setSteps([...steps, { sequence: maxSeq + 10, section_id: 0, operation_code: null, operation_name: "", norm_time_minutes: null, is_final: false }]);
  };

  const moveStep = (index: number, dir: -1 | 1) => {
    if (index + dir < 0 || index + dir >= steps.length) return;
    const next = [...steps];
    [next[index], next[index + dir]] = [next[index + dir], next[index]];
    setSteps(next);
  };

  const removeStep = (index: number) => setSteps(steps.filter((_, i) => i !== index));

  const updateStep = (index: number, patch: Partial<API.StepInput>) => {
    setSteps(steps.map((s, i) => i === index ? { ...s, ...patch } : s));
  };

  const addRule = () => {
    setRules([...rules, { id: Date.now(), route_id: route?.id ?? 0, priority: 0, conditions: [] }]);
  };

  const removeRule = (index: number) => setRules(rules.filter((_, i) => i !== index));

  const addCondition = (ruleIndex: number) => {
    setRules(rules.map((r, i) => i === ruleIndex ? { ...r, conditions: [...r.conditions, { field: "profile_type", operator: "=", value: "" }] } : r));
  };

  const updateCondition = (ruleIndex: number, condIndex: number, patch: Partial<API.RuleCondition>) => {
    setRules(rules.map((r, i) => i === ruleIndex ? {
      ...r, conditions: r.conditions.map((c, j) => j === condIndex ? { ...c, ...patch } : c)
    } : r));
  };

  const removeCondition = (ruleIndex: number, condIndex: number) => {
    setRules(rules.map((r, i) => i === ruleIndex ? { ...r, conditions: r.conditions.filter((_, j) => j !== condIndex) } : r));
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[85vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle>{route ? "Редактирование маршрута" : "Новый маршрут"}</DialogTitle>
        </DialogHeader>

        {/* Tabs */}
        <div className="flex gap-1 border-b">
          {(["info", "steps", "rules"] as const).map((tab) => (
            <button
              key={tab}
              type="button"
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${activeTab === tab ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"}`}
              onClick={() => onTabChange(tab)}
            >
              {tab === "info" ? "Основное" : tab === "steps" ? "Этапы" : "Правила назначения"}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-auto mt-4">
          {activeTab === "info" && (
            <div className="space-y-4">
              <div>
                <label className="text-sm font-medium">Название *</label>
                <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Стандартный алюминий" />
              </div>
              <div>
                <label className="text-sm font-medium">Описание</label>
                <Input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Полный цикл через склад П/Ф" />
              </div>
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} className="h-4 w-4" />
                Активен
              </label>
            </div>
          )}

          {activeTab === "steps" && (
            <div className="space-y-2">
              {steps.map((step, i) => (
                <div key={i} className="flex items-center gap-2 p-2 border rounded">
                  <span className="text-sm font-medium w-8">{i + 1}</span>
                  <select
                    className="h-9 rounded-md border border-input bg-background px-2 text-sm flex-1"
                    value={step.section_id}
                    onChange={(e) => updateStep(i, { section_id: Number(e.target.value) })}
                  >
                    <option value={0}>Участок</option>
                    {sections.map((s) => <option key={s.id} value={s.id}>{s.code} — {s.name}</option>)}
                  </select>
                  <select
                    className="h-9 rounded-md border border-input bg-background px-2 text-sm flex-1"
                    value={step.operation_code ?? ""}
                    onChange={(e) => updateStep(i, { operation_code: e.target.value || null })}
                  >
                    <option value="">Операция</option>
                    <option value="ISSUE_RAW">ISSUE_RAW — Выдача сырья</option>
                    <option value="DRILL">DRILL — Сверловка</option>
                    <option value="PRESS_WINDOW">PRESS_WINDOW — Пресс окно</option>
                    <option value="PRESS_COMB">PRESS_COMB — Пресс гребенка</option>
                    <option value="SHOT">SHOT — Дробеструй</option>
                    <option value="ANOD">ANOD — Анодирование</option>
                    <option value="MOVE_TO_WIP">MOVE_TO_WIP — Передача на п/ф</option>
                    <option value="SAW">SAW — Пила</option>
                    <option value="PACK">PACK — Упаковка</option>
                    <option value="ACCEPT_FINISHED">ACCEPT_FINISHED — Приемка ГП</option>
                  </select>
                  <Input
                    className="w-20 h-9"
                    type="number"
                    placeholder="Мин"
                    value={step.norm_time_minutes ?? ""}
                    onChange={(e) => updateStep(i, { norm_time_minutes: e.target.value ? Number(e.target.value) : null })}
                  />
                  <label className="flex items-center gap-1 text-xs cursor-pointer">
                    <input type="checkbox" checked={step.is_final} onChange={(e) => updateStep(i, { is_final: e.target.checked })} className="h-3.5 w-3.5" />
                    Финал
                  </label>
                  <Button variant="ghost" size="sm" onClick={() => moveStep(i, -1)} disabled={i === 0}><ArrowUp className="h-3.5 w-3.5" /></Button>
                  <Button variant="ghost" size="sm" onClick={() => moveStep(i, 1)} disabled={i === steps.length - 1}><ArrowDown className="h-3.5 w-3.5" /></Button>
                  <Button variant="ghost" size="sm" onClick={() => removeStep(i)}><X className="h-3.5 w-3.5" /></Button>
                </div>
              ))}
              <Button variant="outline" size="sm" onClick={addStep}><Plus className="h-4 w-4 mr-1" />Добавить этап</Button>
            </div>
          )}

          {activeTab === "rules" && (
            <div className="space-y-4">
              {rules.map((rule, ri) => (
                <Card key={ri} className="p-3">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-medium">Правило {ri + 1}</span>
                    <div className="flex items-center gap-2">
                      <label className="text-xs text-muted-foreground">Приоритет:</label>
                      <Input
                        className="w-16 h-7 text-xs"
                        type="number"
                        value={rule.priority}
                        onChange={(e) => setRules(rules.map((r, i) => i === ri ? { ...r, priority: Number(e.target.value) } : r))}
                      />
                      <Button variant="ghost" size="sm" onClick={() => removeRule(ri)}><Trash2 className="h-3.5 w-3.5 text-destructive" /></Button>
                    </div>
                  </div>
                  {rule.conditions.map((cond, ci) => (
                    <div key={ci} className="flex items-center gap-2 mb-1">
                      <select
                        className="h-8 rounded border border-input bg-background px-2 text-xs flex-1"
                        value={cond.field}
                        onChange={(e) => updateCondition(ri, ci, { field: e.target.value })}
                      >
                        {CONDITION_FIELDS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
                      </select>
                      <select
                        className="h-8 rounded border border-input bg-background px-2 text-xs w-28"
                        value={cond.operator}
                        onChange={(e) => updateCondition(ri, ci, { operator: e.target.value as API.RuleCondition["operator"] })}
                      >
                        {OPERATORS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                      </select>
                      <Input
                        className="h-8 text-xs flex-1"
                        value={cond.value}
                        onChange={(e) => updateCondition(ri, ci, { value: e.target.value })}
                        placeholder="Значение"
                      />
                      <Button variant="ghost" size="sm" onClick={() => removeCondition(ri, ci)}><X className="h-3.5 w-3.5" /></Button>
                    </div>
                  ))}
                  <Button variant="ghost" size="sm" className="text-xs" onClick={() => addCondition(ri)}><Plus className="h-3 w-3 mr-1" />Условие</Button>
                </Card>
              ))}
              <Button variant="outline" size="sm" onClick={addRule}><Plus className="h-4 w-4 mr-1" />Добавить правило</Button>
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 pt-2 border-t">
          <Button variant="outline" onClick={() => onOpenChange(false)}>Отмена</Button>
          <Button onClick={handleSave} disabled={saving}>{saving ? "Сохранение..." : "Сохранить"}</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
