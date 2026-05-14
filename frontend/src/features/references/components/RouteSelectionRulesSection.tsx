import { useCallback, useEffect, useMemo, useState } from "react";
import { Pencil, Plus, RefreshCw, Trash2 } from "lucide-react";
import * as RoutesAPI from "@/shared/api/routes";
import * as SectionsAPI from "@/shared/api/sections";
import { getErrorMessage } from "@/shared/api/client";
import { Badge } from "@/shared/ui/Badge";
import { Button } from "@/shared/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/ui/Card";
import { Checkbox } from "@/shared/ui/Checkbox";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/shared/ui/Dialog";
import { Input } from "@/shared/ui/Input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/shared/ui/Select";
import { Table, TableBody, TableCell, TableContainer, TableHead, TableHeader, TableRow } from "@/shared/ui/Table";
import { toast } from "@/shared/ui/use-toast";

type Props = {
  refreshKey: number;
};

const sourceLabels: Record<RoutesAPI.RouteSelectionCondition["source"], string> = {
  excel: "Excel",
  payload: "Payload",
  product: "Product",
};

const operatorLabels: Record<RoutesAPI.RouteSelectionCondition["operator"], string> = {
  equals: "равно",
  not_equals: "не равно",
  contains: "содержит",
  not_contains: "не содержит",
  in: "в списке",
  not_in: "не в списке",
  empty: "пусто",
  not_empty: "не пусто",
  regex: "regex",
};

const actionLabels: Record<RoutesAPI.RouteSelectionAction["action"], string> = {
  require_section: "Добавить",
  exclude_section: "Исключить",
};

const emptyCondition: RoutesAPI.RouteSelectionCondition = {
  source: "payload",
  field_path: "operation",
  operator: "contains",
  value: "",
  case_sensitive: false,
};

const emptyAction: RoutesAPI.RouteSelectionAction = {
  action: "require_section",
  section_id: 0,
};

const emptyForm: RoutesAPI.RouteSelectionRuleInput = {
  code: null,
  name: "",
  priority: 0,
  is_active: true,
  conditions: [],
  actions: [{ ...emptyAction }],
};

export function RouteSelectionRulesSection({ refreshKey }: Props) {
  const [rules, setRules] = useState<RoutesAPI.RouteSelectionRule[]>([]);
  const [sections, setSections] = useState<SectionsAPI.Section[]>([]);
  const [loading, setLoading] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<RoutesAPI.RouteSelectionRule | null>(null);
  const [form, setForm] = useState<RoutesAPI.RouteSelectionRuleInput>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [deletingRuleId, setDeletingRuleId] = useState<number | null>(null);

  const activeSections = useMemo(() => sections.filter((section) => section.is_active), [sections]);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [loadedRules, loadedSections] = await Promise.all([
        RoutesAPI.listRouteSelectionRules(),
        SectionsAPI.listSections(),
      ]);
      setRules(loadedRules);
      setSections(loadedSections);
    } catch (e) {
      toast({ variant: "destructive", title: "Ошибка загрузки правил выбора маршрута", description: getErrorMessage(e) });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData, refreshKey]);

  const normalizeForm = (rule: RoutesAPI.RouteSelectionRuleInput): RoutesAPI.RouteSelectionRuleInput => ({
    ...rule,
    code: rule.code?.trim() || null,
    name: rule.name.trim(),
    actions: rule.actions.map((action) => ({
      action: action.action,
      section_id: Number(action.section_id),
    })),
    conditions: rule.conditions.map((condition) => ({
      ...condition,
      field_path: condition.field_path.trim(),
      value: condition.operator === "empty" || condition.operator === "not_empty" ? null : condition.value,
    })),
  });

  const openCreateDialog = () => {
    setEditingRule(null);
    setForm({
      ...emptyForm,
      actions: [{ ...emptyAction, section_id: activeSections[0]?.id ?? 0 }],
    });
    setDialogOpen(true);
  };

  const openEditDialog = (rule: RoutesAPI.RouteSelectionRule) => {
    setEditingRule(rule);
    setForm({
      code: rule.code,
      name: rule.name,
      priority: rule.priority,
      is_active: rule.is_active,
      conditions: rule.conditions.map((condition) => ({ ...condition })),
      actions: rule.actions.map((action) => ({ action: action.action, section_id: action.section_id })),
    });
    setDialogOpen(true);
  };

  const validateForm = () => {
    const normalized = normalizeForm(form);
    if (!normalized.name) return "Название обязательно";
    if (!Number.isFinite(normalized.priority)) return "Приоритет обязателен";
    if (!normalized.actions.length) return "Добавьте хотя бы одно действие";
    if (normalized.actions.some((action) => !action.section_id)) return "В каждом действии должен быть выбран участок";
    if (normalized.conditions.some((condition) => !condition.field_path)) return "В каждом условии должно быть поле";
    const needsValue = normalized.conditions.some((condition) => !["empty", "not_empty"].includes(condition.operator) && (condition.value === null || String(condition.value ?? "").trim() === ""));
    if (needsValue) return "В условиях с выбранным оператором нужно значение";
    return null;
  };

  const handleSave = async () => {
    const validationError = validateForm();
    if (validationError) {
      toast({ variant: "destructive", title: validationError });
      return;
    }
    const payload = normalizeForm(form);
    setSaving(true);
    try {
      if (editingRule) {
        await RoutesAPI.updateRouteSelectionRule(editingRule.id, payload);
        toast({ title: "Правило обновлено", variant: "success" });
      } else {
        await RoutesAPI.createRouteSelectionRule(payload);
        toast({ title: "Правило создано", variant: "success" });
      }
      setDialogOpen(false);
      await loadData();
    } catch (e) {
      toast({ variant: "destructive", title: "Ошибка сохранения правила", description: getErrorMessage(e) });
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (rule: RoutesAPI.RouteSelectionRule) => {
    if (!window.confirm("Удалить правило выбора маршрута?")) return;
    setDeletingRuleId(rule.id);
    try {
      await RoutesAPI.deleteRouteSelectionRule(rule.id);
      setRules((current) => current.filter((item) => item.id !== rule.id));
      toast({ title: "Правило удалено", variant: "success" });
    } catch (e) {
      toast({ variant: "destructive", title: "Ошибка удаления правила", description: getErrorMessage(e) });
    } finally {
      setDeletingRuleId(null);
    }
  };

  const updateCondition = (index: number, patch: Partial<RoutesAPI.RouteSelectionCondition>) => {
    setForm((current) => ({
      ...current,
      conditions: current.conditions.map((condition, idx) => (idx === index ? { ...condition, ...patch } : condition)),
    }));
  };

  const updateAction = (index: number, patch: Partial<RoutesAPI.RouteSelectionAction>) => {
    setForm((current) => ({
      ...current,
      actions: current.actions.map((action, idx) => (idx === index ? { ...action, ...patch } : action)),
    }));
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <CardTitle>Правила выбора маршрута</CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">{rules.length} правил</p>
          </div>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={() => void loadData()} disabled={loading}>
              <RefreshCw className="mr-1 h-4 w-4" />
              Обновить
            </Button>
            <Button size="sm" onClick={openCreateDialog} disabled={!activeSections.length}>
              <Plus className="mr-1 h-4 w-4" />
              Создать правило
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <TableContainer className="rounded-md">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>priority</TableHead>
                <TableHead>name</TableHead>
                <TableHead>is_active</TableHead>
                <TableHead>Условия</TableHead>
                <TableHead>Действия</TableHead>
                <TableHead className="text-right">Действия</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rules.map((rule) => (
                <TableRow key={rule.id}>
                  <TableCell className="font-medium">{rule.priority}</TableCell>
                  <TableCell>
                    <div className="font-medium">{rule.name}</div>
                    {rule.code && <div className="text-xs text-muted-foreground">{rule.code}</div>}
                  </TableCell>
                  <TableCell>
                    <Badge variant={rule.is_active ? "default" : "secondary"}>{rule.is_active ? "Активно" : "Отключено"}</Badge>
                  </TableCell>
                  <TableCell>{rule.conditions.length || "Всегда"}</TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {rule.actions.map((action, index) => (
                        <Badge key={`${rule.id}-${index}`} variant={action.action === "require_section" ? "default" : "secondary"}>
                          {actionLabels[action.action]} {action.section_code ?? action.section_id}
                        </Badge>
                      ))}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-2">
                      <Button size="sm" variant="outline" onClick={() => openEditDialog(rule)}>
                        <Pencil className="mr-1 h-4 w-4" />
                        Редактировать
                      </Button>
                      <Button size="sm" variant="destructive" onClick={() => void handleDelete(rule)} disabled={deletingRuleId === rule.id}>
                        <Trash2 className="mr-1 h-4 w-4" />
                        Удалить
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
              {!loading && rules.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="py-6 text-center text-muted-foreground">Правил выбора маршрута нет</TableCell>
                </TableRow>
              )}
              {loading && (
                <TableRow>
                  <TableCell colSpan={6} className="py-6 text-center text-muted-foreground">Загрузка...</TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </CardContent>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="w-[min(900px,calc(100vw-2rem))] max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editingRule ? "Редактировать правило" : "Создать правило"}</DialogTitle>
          </DialogHeader>

          <div className="grid gap-4">
            <div className="grid gap-3 md:grid-cols-[1fr_140px_140px]">
              <label className="grid gap-1.5 text-sm font-medium">
                name
                <Input value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} />
              </label>
              <label className="grid gap-1.5 text-sm font-medium">
                priority
                <Input type="number" value={form.priority} onChange={(event) => setForm((current) => ({ ...current, priority: Number(event.target.value) }))} />
              </label>
              <label className="flex items-end gap-2 pb-2 text-sm font-medium">
                <Checkbox checked={form.is_active} onCheckedChange={(checked) => setForm((current) => ({ ...current, is_active: checked === true }))} />
                is_active
              </label>
            </div>

            <label className="grid gap-1.5 text-sm font-medium">
              code
              <Input value={form.code ?? ""} onChange={(event) => setForm((current) => ({ ...current, code: event.target.value }))} placeholder="Опционально" />
            </label>

            <div className="grid gap-2">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold">Условия</h3>
                <Button size="sm" variant="outline" onClick={() => setForm((current) => ({ ...current, conditions: [...current.conditions, { ...emptyCondition }] }))}>
                  <Plus className="mr-1 h-4 w-4" />
                  Добавить условие
                </Button>
              </div>
              {form.conditions.map((condition, index) => (
                <div key={index} className="grid gap-2 rounded-md border p-3 md:grid-cols-[120px_1fr_160px_1fr_110px_auto] md:items-end">
                  <label className="grid gap-1.5 text-xs font-medium">
                    source
                    <Select value={condition.source} onValueChange={(value) => updateCondition(index, { source: value as RoutesAPI.RouteSelectionCondition["source"] })}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {(Object.keys(sourceLabels) as RoutesAPI.RouteSelectionCondition["source"][]).map((value) => <SelectItem key={value} value={value}>{sourceLabels[value]}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </label>
                  <label className="grid gap-1.5 text-xs font-medium">
                    field_path
                    <Input value={condition.field_path} onChange={(event) => updateCondition(index, { field_path: event.target.value })} />
                  </label>
                  <label className="grid gap-1.5 text-xs font-medium">
                    operator
                    <Select value={condition.operator} onValueChange={(value) => updateCondition(index, { operator: value as RoutesAPI.RouteSelectionCondition["operator"] })}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {(Object.keys(operatorLabels) as RoutesAPI.RouteSelectionCondition["operator"][]).map((value) => <SelectItem key={value} value={value}>{operatorLabels[value]}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </label>
                  <label className="grid gap-1.5 text-xs font-medium">
                    value
                    <Input disabled={condition.operator === "empty" || condition.operator === "not_empty"} value={String(condition.value ?? "")} onChange={(event) => updateCondition(index, { value: event.target.value })} />
                  </label>
                  <label className="flex items-center gap-2 pb-2 text-xs font-medium">
                    <Checkbox checked={condition.case_sensitive} onCheckedChange={(checked) => updateCondition(index, { case_sensitive: checked === true })} />
                    case
                  </label>
                  <Button size="sm" variant="outline" onClick={() => setForm((current) => ({ ...current, conditions: current.conditions.filter((_, idx) => idx !== index) }))}>
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              ))}
              {form.conditions.length === 0 && <div className="rounded-md border p-3 text-sm text-muted-foreground">Правило будет применяться всегда.</div>}
            </div>

            <div className="grid gap-2">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold">Действия по участкам</h3>
                <Button size="sm" variant="outline" onClick={() => setForm((current) => ({ ...current, actions: [...current.actions, { ...emptyAction, section_id: activeSections[0]?.id ?? 0 }] }))}>
                  <Plus className="mr-1 h-4 w-4" />
                  Добавить действие
                </Button>
              </div>
              {form.actions.map((action, index) => (
                <div key={index} className="grid gap-2 rounded-md border p-3 md:grid-cols-[200px_1fr_auto] md:items-end">
                  <label className="grid gap-1.5 text-xs font-medium">
                    action
                    <Select value={action.action} onValueChange={(value) => updateAction(index, { action: value as RoutesAPI.RouteSelectionAction["action"] })}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {(Object.keys(actionLabels) as RoutesAPI.RouteSelectionAction["action"][]).map((value) => <SelectItem key={value} value={value}>{actionLabels[value]}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </label>
                  <label className="grid gap-1.5 text-xs font-medium">
                    section
                    <Select value={action.section_id ? String(action.section_id) : undefined} onValueChange={(value) => updateAction(index, { section_id: Number(value) })}>
                      <SelectTrigger><SelectValue placeholder="Участок" /></SelectTrigger>
                      <SelectContent>
                        {activeSections.map((section) => <SelectItem key={section.id} value={String(section.id)}>{section.code} · {section.name}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </label>
                  <Button size="sm" variant="outline" onClick={() => setForm((current) => ({ ...current, actions: current.actions.filter((_, idx) => idx !== index) }))}>
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              ))}
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)} disabled={saving}>Отмена</Button>
            <Button onClick={() => void handleSave()} disabled={saving}>{saving ? "Сохранение..." : "Сохранить"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
