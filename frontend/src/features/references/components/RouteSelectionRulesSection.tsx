import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import * as RoutesAPI from "@/shared/api/routes";
import * as SectionsAPI from "@/shared/api/sections";
import * as ImportTemplatesAPI from "@/shared/api/importTemplates";
import { getErrorMessage } from "@/shared/api/client";
import { getSectionOperations, type SectionOperation } from "@/shared/api/shopfloor";
import { Badge } from "@/shared/ui/Badge";
import { Button } from "@/shared/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/ui/Card";
import { Checkbox } from "@/shared/ui/Checkbox";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/shared/ui/Dialog";
import { Input } from "@/shared/ui/Input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/shared/ui/Select";
import { SectionSelect } from "@/shared/ui/SectionSelect";
import { Table, TableBody, TableCell, TableContainer, TableHead, TableHeader, TableRow } from "@/shared/ui/Table";
import { toast } from "@/shared/ui/use-toast";

type Props = {
  refreshKey: number;
};

type RuleScope = "global" | "profile";
type RuleSource = RoutesAPI.RouteSelectionCondition["source"];
type RulePhase = "normalize" | "route_select";

const phaseLabels: Record<RulePhase, string> = {
  normalize: "Нормализация",
  route_select: "Выбор маршрута",
};

type FieldOption = {
  field_path: string;
  label: string;
  hint?: string;
};

type ExcelColumnSpec = {
  index: number;
  letter: string;
  header: string;
  field_path: string;
};

type ProfileFormState = {
  code: string;
  name: string;
  priority: number;
  is_active: boolean;
  import_template_id: number | null;
  excel_column_passport: ExcelColumnSpec[];
  excel_passport_meta: Record<string, unknown>;
};

const sourceLabels: Record<RuleSource, string> = {
  excel: "Колонки Excel",
  payload: "Нормализованные поля",
  product: "Поля продукта",
  ctx: "Контекст",
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
  set: "Установить (set)",
  add: "Добавить в список (add)",
  remove: "Удалить из списка (remove)",
};

const isDslAction = (action: string): boolean => action === "set" || action === "add" || action === "remove";
const isSectionAction = (action: string): boolean => action === "require_section" || action === "exclude_section";

const HEADER_KEY_BY_NAME: Record<string, string> = {
  "артикул": "sku",
  "пополнение": "replenishment",
  "наименование": "product_name",
  "остатки сырья на ктм": "raw_stock_ktm",
  "цвет": "color",
  "кол-во шт. в 2,7": "input_quantity",
  "длина, м": "input_length",
  "пробивка/сверловка": "operation",
  "упаковка": "packaging",
  "примечание": "note",
  "длина после упак, м": "output_length",
  "кол-во штук готовой продукции": "output_quantity",
  "запад": "west_quantity",
  "восток": "east_quantity",
  "вид конечного продукта": "output_kind",
  "комментарии": "comments",
  "упаковка в 1,8": "packaging_1_8_quantity",
  "добавить": "add_quantity",
  "срок готовности": "due_date",
  "клиент": "customer",
  "приоритет": "priority",
  "заказ": "order_ref",
};

const payloadFieldOptions: FieldOption[] = [
  { field_path: "operation", label: "Пробивка/сверловка (сырой текст)", hint: "Текст первичной операции из Excel" },
  { field_path: "operation_code", label: "Код первичной операции", hint: "DRILL / PRESS_WINDOW / PRESS_COMB / PACK" },
  { field_path: "output_kind", label: "Вид конечного продукта (норм.)", hint: "finished_good или semi_finished_shipment" },
  { field_path: "output_kind_raw", label: "Вид конечного продукта (как в файле)", hint: "Например: ГП или П/ф" },
  { field_path: "additional_pack_operations", label: "Доп. упаковочные операции", hint: "Список PACK_* операций" },
  { field_path: "packaging", label: "Упаковка", hint: "Текст из колонки Упаковка" },
  { field_path: "color", label: "Цвет", hint: "Цвет из строки импорта" },
  { field_path: "customer", label: "Клиент", hint: "Клиент из строки импорта" },
  { field_path: "priority", label: "Приоритет", hint: "Приоритет позиции из импорта" },
];

const productFieldOptions: FieldOption[] = [
  { field_path: "sku", label: "Артикул продукта (sku)" },
  { field_path: "name", label: "Название продукта" },
  { field_path: "type", label: "Тип продукта", hint: "finished_good / semi_finished / component / material" },
  { field_path: "is_active", label: "Продукт активен (is_active)" },
  { field_path: "skip_shot_blast", label: "Без дробеструя (skip_shot_blast)" },
  { field_path: "is_paired_profile", label: "Парный профиль (is_paired_profile)" },
  { field_path: "is_laminated", label: "Ламинированный (is_laminated)" },
];

const valuePresets: Record<string, Array<{ label: string; value: unknown }>> = {
  "payload:output_kind": [
    { label: "ГП (finished_good)", value: "finished_good" },
    { label: "П/ф (semi_finished_shipment)", value: "semi_finished_shipment" },
  ],
  "payload:output_kind_raw": [
    { label: "ГП", value: "ГП" },
    { label: "П/ф", value: "П/ф" },
  ],
  "product:skip_shot_blast": [
    { label: "Да (true)", value: true },
    { label: "Нет (false)", value: false },
  ],
  "product:is_active": [
    { label: "Да (true)", value: true },
    { label: "Нет (false)", value: false },
  ],
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

const emptyDslAction: RoutesAPI.RouteSelectionAction = {
  action: "set",
  path: "ctx.",
  value: null,
};

const emptyForm: RoutesAPI.RouteSelectionRuleInput = {
  code: null,
  name: "",
  profile_id: null,
  priority: 0,
  is_active: true,
  phase: "route_select",
  conditions: [],
  actions: [{ ...emptyAction }],
};

const emptyProfileForm: ProfileFormState = {
  code: "",
  name: "",
  priority: 0,
  is_active: true,
  import_template_id: null,
  excel_column_passport: [],
  excel_passport_meta: {},
};

function normalizeHeader(value: string): string {
  return value.toLowerCase().replace(/\u00a0/g, " ").trim().replace(/\s+/g, " ");
}

function toColumnLetter(index: number): string {
  let n = Math.max(1, Math.floor(index));
  let out = "";
  while (n > 0) {
    const rem = (n - 1) % 26;
    out = String.fromCharCode(65 + rem) + out;
    n = Math.floor((n - 1) / 26);
  }
  return out;
}

function toFieldPath(header: string, index: number): string {
  const normalized = normalizeHeader(header);
  return HEADER_KEY_BY_NAME[normalized] ?? `column_${index}`;
}

type PassportBindingStatus = {
  level: "ok" | "warning" | "info";
  title: string;
  description: string;
};

function parseColumnTokenToIndex(token: string): number | null {
  const clean = token.trim();
  if (!clean) return null;
  if (/^\d+$/.test(clean)) {
    const parsed = Number(clean);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }
  if (!/^[A-Za-z]+$/.test(clean)) return null;
  let out = 0;
  for (const ch of clean.toUpperCase()) {
    out = out * 26 + (ch.charCodeAt(0) - 64);
  }
  return out > 0 ? out : null;
}

function looksLikeColumnKey(value: string): boolean {
  const clean = value.trim();
  return /^[A-Za-z]+$/.test(clean) || /^\d+$/.test(clean);
}

function buildPassportFromTemplateMapping(mapping: ImportTemplatesAPI.ImportTemplate["column_mapping"]): ExcelColumnSpec[] {
  const usedIndexes = new Set<number>();
  const prepared = Object.entries(mapping ?? {}).map(([rawKey, rawValue]) => {
    const key = rawKey.trim();
    if (!key) return null;

    let fieldPath = key;
    let header = key;
    let columnToken = "";
    if (typeof rawValue === "string") {
      const value = rawValue.trim();
      if (looksLikeColumnKey(key) && value) {
        fieldPath = value;
        header = value;
        columnToken = key;
      } else {
        header = value || key;
      }
    } else if (rawValue && typeof rawValue === "object") {
      const row = rawValue as { header?: string; column?: string };
      header = String(row.header ?? key).trim() || key;
      columnToken = String(row.column ?? "").trim();
    }

    const parsedIndex = parseColumnTokenToIndex(columnToken);
    if (parsedIndex) usedIndexes.add(parsedIndex);
    return {
      field_path: fieldPath,
      header,
      parsedIndex,
    };
  }).filter((item): item is { field_path: string; header: string; parsedIndex: number | null } => item !== null);

  let nextIndex = 1;
  return prepared.map((item) => {
    let index = item.parsedIndex;
    if (!index) {
      while (usedIndexes.has(nextIndex)) nextIndex += 1;
      index = nextIndex;
      usedIndexes.add(index);
      nextIndex += 1;
    }
    return {
      index,
      letter: toColumnLetter(index),
      header: item.header,
      field_path: item.field_path,
    };
  }).sort((a, b) => a.index - b.index);
}

function getPassportBindingStatus(
  importTemplateId: number | null,
  passport: ExcelColumnSpec[],
  meta: Record<string, unknown>,
  templateName: string | null,
): PassportBindingStatus {
  if (!importTemplateId) {
    return {
      level: "info",
      title: "Шаблон импорта не выбран",
      description: "Можно работать с полями payload/product. Для стабильных Excel-условий рекомендуется выбрать шаблон и синхронизировать паспорт.",
    };
  }
  if (!passport.length) {
    return {
      level: "warning",
      title: "Паспорт колонок не задан",
      description: templateName
        ? `Выбран шаблон «${templateName}», но паспорт пуст. Excel-условия будут ограничены до заполнения паспорта.`
        : "Шаблон выбран, но паспорт пуст. Excel-условия будут ограничены до заполнения паспорта.",
    };
  }
  const metaTemplateId = Number(meta.import_template_id ?? NaN);
  if (Number.isFinite(metaTemplateId) && metaTemplateId === importTemplateId) {
    return {
      level: "ok",
      title: "Паспорт синхронизирован с шаблоном",
      description: templateName
        ? `Паспорт привязан к шаблону «${templateName}». Колонок: ${passport.length}.`
        : `Паспорт привязан к текущему шаблону. Колонок: ${passport.length}.`,
    };
  }
  return {
    level: "warning",
    title: "Паспорт может быть устаревшим",
    description: templateName
      ? `Выбран шаблон «${templateName}», но метаданные паспорта не совпадают. Нажмите «Применить».`
      : "Метаданные паспорта не совпадают с выбранным шаблоном. Рекомендуется обновить паспорт вручную.",
  };
}

function passportStatusClassName(level: PassportBindingStatus["level"]): string {
  if (level === "ok") return "border-emerald-300 bg-emerald-50 text-emerald-800";
  if (level === "warning") return "border-amber-300 bg-amber-50 text-amber-800";
  return "border-slate-300 bg-slate-50 text-slate-700";
}

type ConditionRowProps = {
  index: number;
  condition: RoutesAPI.RouteSelectionCondition;
  scope: RuleScope;
  ruleExcelColumns: ExcelColumnSpec[];
  fieldOptionsBySource: Record<RuleSource, FieldOption[]>;
  valuePresets: Record<string, Array<{ label: string; value: unknown }>>;
  sourceOptionsForCondition: (condition: RoutesAPI.RouteSelectionCondition) => RuleSource[];
  onUpdateCondition: (index: number, patch: Partial<RoutesAPI.RouteSelectionCondition>) => void;
  onApplyExcelColumn: (index: number, columnIndex: number) => void;
  onApplyValuePreset: (index: number, value: unknown) => void;
  onRemoveCondition: (index: number) => void;
};

function ConditionRow({
  index,
  condition,
  scope,
  ruleExcelColumns,
  fieldOptionsBySource,
  valuePresets: conditionValuePresets,
  sourceOptionsForCondition,
  onUpdateCondition,
  onApplyExcelColumn,
  onApplyValuePreset,
  onRemoveCondition,
}: ConditionRowProps) {
  const selectedFieldHint = fieldOptionsBySource[condition.source].find((option) => option.field_path === condition.field_path)?.hint;
  const presetKey = `${condition.source}:${condition.field_path}`;

  return (
    <tr className="border-b last:border-b-0 align-top">
      <td className="p-1 min-w-[170px]">
        <Select
          value={condition.source}
          onValueChange={(value) => {
            const nextSource = value as RuleSource;
            if (nextSource === "excel") {
              const preferred = ruleExcelColumns.find((column) => column.field_path === condition.field_path) ?? ruleExcelColumns[0];
              onUpdateCondition(index, {
                source: nextSource,
                field_path: preferred?.field_path ?? condition.field_path ?? "",
                excel_column_index: preferred?.index ?? null,
                excel_column_letter: preferred?.letter ?? null,
                excel_header: preferred?.header ?? null,
              });
              return;
            }
            onUpdateCondition(index, {
              source: nextSource,
              excel_column_index: null,
              excel_column_letter: null,
              excel_header: null,
            });
          }}
        >
          <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            {sourceOptionsForCondition(condition).map((value) => (
              <SelectItem key={value} value={value}>{sourceLabels[value]}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </td>
      <td className="p-1 min-w-[280px]">
        <div className="grid gap-1">
          {condition.source === "excel" ? (
            <>
              <Select
                value={condition.excel_column_index ? String(condition.excel_column_index) : "__custom__"}
                onValueChange={(value) => {
                  if (value === "__custom__") {
                    onUpdateCondition(index, {
                      excel_column_index: null,
                      excel_column_letter: null,
                      excel_header: null,
                    });
                    return;
                  }
                  onApplyExcelColumn(index, Number(value));
                }}
                disabled={scope !== "profile" || ruleExcelColumns.length === 0}
              >
                <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {condition.excel_column_index && !ruleExcelColumns.some((column) => column.index === condition.excel_column_index) && (
                    <SelectItem value={String(condition.excel_column_index)}>
                      {condition.excel_column_index} / {condition.excel_column_letter ?? "?"} / {condition.excel_header ?? "—"}
                    </SelectItem>
                  )}
                  {ruleExcelColumns.map((column) => (
                    <SelectItem key={column.index} value={String(column.index)}>
                      {column.index} / {column.letter} / {column.header}
                    </SelectItem>
                  ))}
                  {ruleExcelColumns.length === 0 && (
                    <SelectItem value="__empty__" disabled>
                      Паспорт колонок не задан
                    </SelectItem>
                  )}
                  <SelectItem value="__custom__">Кастомная колонка</SelectItem>
                </SelectContent>
              </Select>
              {condition.excel_column_index ? (
                <Input value={condition.field_path} readOnly className="h-7 text-xs bg-muted/40" />
              ) : (
                <Input
                  value={condition.field_path}
                  onChange={(event) => onUpdateCondition(index, { field_path: event.target.value })}
                  placeholder="Ключ колонки"
                  className="h-7 text-xs"
                />
              )}
            </>
          ) : (
            <>
              <Input
                list={`field-path-options-${index}`}
                value={condition.field_path}
                onChange={(event) => onUpdateCondition(index, { field_path: event.target.value })}
                placeholder="Например: output_kind"
                className="h-8 text-xs"
              />
              <datalist id={`field-path-options-${index}`}>
                {fieldOptionsBySource[condition.source].map((option) => (
                  <option key={`${condition.source}-${option.field_path}`} value={option.field_path}>
                    {option.label}
                  </option>
                ))}
              </datalist>
            </>
          )}
          {selectedFieldHint ? <span className="text-[11px] text-muted-foreground">{selectedFieldHint}</span> : null}
        </div>
      </td>
      <td className="p-1 min-w-[150px]">
        <Select value={condition.operator} onValueChange={(value) => onUpdateCondition(index, { operator: value as RoutesAPI.RouteSelectionCondition["operator"] })}>
          <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            {(Object.keys(operatorLabels) as RoutesAPI.RouteSelectionCondition["operator"][]).map((value) => (
              <SelectItem key={value} value={value}>{operatorLabels[value]}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </td>
      <td className="p-1 min-w-[220px]">
        <div className="grid gap-1">
          <Input
            disabled={condition.operator === "empty" || condition.operator === "not_empty"}
            value={String(condition.value ?? "")}
            onChange={(event) => onUpdateCondition(index, { value: event.target.value })}
            className="h-8 text-xs"
          />
          {condition.operator !== "empty" && condition.operator !== "not_empty" && conditionValuePresets[presetKey]?.length ? (
            <div className="flex flex-wrap gap-1">
              {conditionValuePresets[presetKey].map((preset, presetIndex) => (
                <button
                  key={`${presetKey}:${presetIndex}`}
                  type="button"
                  onClick={() => onApplyValuePreset(index, preset.value)}
                  className="rounded border px-1.5 py-0.5 text-[10px] hover:bg-accent"
                >
                  {preset.label}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      </td>
      <td className="p-1 w-[64px]">
        <div className="flex items-center justify-center gap-1 pt-2">
          <Checkbox checked={condition.case_sensitive} onCheckedChange={(checked) => onUpdateCondition(index, { case_sensitive: checked === true })} />
          <span className="text-[10px] text-muted-foreground">Aa</span>
        </div>
      </td>
      <td className="p-1 w-[52px]">
        <Button size="sm" variant="ghost" className="h-8 w-8 p-0 text-red-600" onClick={() => onRemoveCondition(index)}>
          <Trash2 className="h-4 w-4" />
        </Button>
      </td>
    </tr>
  );
}

export function RouteSelectionRulesSection({ refreshKey }: Props) {
  const [rules, setRules] = useState<RoutesAPI.RouteSelectionRule[]>([]);
  const [sections, setSections] = useState<SectionsAPI.Section[]>([]);
  const [profiles, setProfiles] = useState<RoutesAPI.RouteRuleProfile[]>([]);
  const [importTemplates, setImportTemplates] = useState<ImportTemplatesAPI.ImportTemplate[]>([]);
  const [loading, setLoading] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<RoutesAPI.RouteSelectionRule | null>(null);
  const [form, setForm] = useState<RoutesAPI.RouteSelectionRuleInput>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [deletingRuleId, setDeletingRuleId] = useState<number | null>(null);
  const [scope, setScope] = useState<RuleScope>("global");
  const [selectedProfileId, setSelectedProfileId] = useState<number | null>(null);

  const [profileDialogOpen, setProfileDialogOpen] = useState(false);
  const [editingProfile, setEditingProfile] = useState<RoutesAPI.RouteRuleProfile | null>(null);
  const [profileForm, setProfileForm] = useState<ProfileFormState>(emptyProfileForm);
  const [savingProfile, setSavingProfile] = useState(false);
  const [deletingProfileId, setDeletingProfileId] = useState<number | null>(null);

  // Cache: sectionId -> operations list
  const [sectionOps, setSectionOps] = useState<Record<number, SectionOperation[]>>({});
  const fetchedSectionsRef = useRef<Set<number>>(new Set());

  const activeSections = useMemo(() => sections.filter((section) => section.is_active), [sections]);
  const selectedProfile = useMemo(
    () => profiles.find((profile) => profile.id === selectedProfileId) ?? null,
    [profiles, selectedProfileId],
  );
  const ruleExcelColumns = useMemo<ExcelColumnSpec[]>(
    () => (selectedProfile?.excel_column_passport ?? []).map((column) => ({
      index: column.index,
      letter: column.letter,
      header: column.header,
      field_path: column.field_path,
    })),
    [selectedProfile],
  );
  const fieldOptionsBySource = useMemo<Record<RuleSource, FieldOption[]>>(() => {
    const excel: FieldOption[] = ruleExcelColumns.map((column) => ({
      field_path: column.field_path,
      label: `${column.index}. ${column.letter} · ${column.header} (${column.field_path})`,
    }));
    return {
      excel,
      payload: payloadFieldOptions,
      product: productFieldOptions,
      ctx: [],
    };
  }, [ruleExcelColumns]);
  const selectedProfileTemplate = useMemo(
    () => importTemplates.find((item) => item.id === selectedProfile?.import_template_id) ?? null,
    [importTemplates, selectedProfile?.import_template_id],
  );
  const selectedProfilePassportStatus = useMemo(
    () => getPassportBindingStatus(
      selectedProfile?.import_template_id ?? null,
      selectedProfile?.excel_column_passport ?? [],
      (selectedProfile?.excel_passport_meta ?? {}) as Record<string, unknown>,
      selectedProfileTemplate?.name ?? null,
    ),
    [selectedProfile, selectedProfileTemplate?.name],
  );
  const profileFormTemplate = useMemo(
    () => importTemplates.find((item) => item.id === profileForm.import_template_id) ?? null,
    [importTemplates, profileForm.import_template_id],
  );
  const profileFormPassportStatus = useMemo(
    () => getPassportBindingStatus(
      profileForm.import_template_id,
      profileForm.excel_column_passport,
      profileForm.excel_passport_meta,
      profileFormTemplate?.name ?? null,
    ),
    [profileForm.excel_column_passport, profileForm.excel_passport_meta, profileForm.import_template_id, profileFormTemplate?.name],
  );

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [loadedSections, loadedProfiles, loadedTemplates] = await Promise.all([
        SectionsAPI.listSections(),
        RoutesAPI.listRouteRuleProfiles(),
        ImportTemplatesAPI.listImportTemplates(),
      ]);
      setSections(loadedSections);
      setProfiles(loadedProfiles);
      setImportTemplates(loadedTemplates);
    } catch (e) {
      toast({ variant: "destructive", title: "Ошибка загрузки данных", description: getErrorMessage(e) });
    } finally {
      setLoading(false);
    }
  }, []);

  const loadRules = useCallback(async () => {
    try {
      const params: { scope: "global" | "profile" | "all"; profile_id?: number } = {
        scope: scope === "global" ? "global" : "profile",
      };
      if (scope === "profile" && selectedProfileId) {
        params.profile_id = selectedProfileId;
      }
      const loadedRules = await RoutesAPI.listRouteSelectionRules(params);
      setRules(loadedRules);
    } catch (e) {
      toast({ variant: "destructive", title: "Ошибка загрузки правил", description: getErrorMessage(e) });
    }
  }, [scope, selectedProfileId]);

  const fetchSectionOperations = useCallback(async (sectionId: number) => {
    if (fetchedSectionsRef.current.has(sectionId)) return;
    fetchedSectionsRef.current.add(sectionId);
    try {
      const ops = await getSectionOperations(sectionId);
      setSectionOps((prev) => ({ ...prev, [sectionId]: ops }));
    } catch (e) {
      setSectionOps((prev) => ({ ...prev, [sectionId]: [] }));
    }
  }, []);

  // Auto-fetch operations for section_ids that are already in form actions
  useEffect(() => {
    const sectionIds = new Set<number>();
    for (const action of form.actions) {
      if (isSectionAction(action.action) && action.section_id) {
        sectionIds.add(action.section_id);
      }
    }
    for (const sectionId of sectionIds) {
      if (!fetchedSectionsRef.current.has(sectionId)) {
        fetchedSectionsRef.current.add(sectionId);
        getSectionOperations(sectionId)
          .then((ops) => {
            setSectionOps((prev) => ({ ...prev, [sectionId]: ops }));
          })
          .catch(() => {
            setSectionOps((prev) => ({ ...prev, [sectionId]: [] }));
          });
      }
    }
  }, [form.actions]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const hasAutoSwitchedRef = useRef(false);

  useEffect(() => {
    void loadRules();
  }, [loadRules, refreshKey]);

  useEffect(() => {
    if (!hasAutoSwitchedRef.current && scope === "global" && rules.length === 0 && profiles.length > 0) {
      const firstWithRules = profiles.find((p) => p.is_active);
      if (firstWithRules) {
        hasAutoSwitchedRef.current = true;
        setScope("profile");
        setSelectedProfileId(firstWithRules.id);
      }
    }
  }, [rules, profiles, scope]);

  const normalizeForm = (rule: RoutesAPI.RouteSelectionRuleInput): RoutesAPI.RouteSelectionRuleInput => ({
    ...rule,
    code: rule.code?.trim() || null,
    name: rule.name.trim(),
    phase: rule.phase ?? "route_select",
    profile_id: scope === "profile" && selectedProfileId ? selectedProfileId : null,
    actions: rule.actions.map((action) => {
      if (isDslAction(action.action)) {
        return {
          action: action.action,
          section_id: null,
          operation_code: null,
          path: action.path?.trim() || null,
          value: action.value,
        };
      }
      if (isSectionAction(action.action)) {
        return {
          action: action.action,
          section_id: Number(action.section_id),
          operation_code: action.operation_code?.trim() || null,
          path: null,
          value: null,
        };
      }
      return {
        action: action.action,
        section_id: Number(action.section_id),
        operation_code: null,
        path: null,
        value: null,
      };
    }),
    conditions: rule.conditions.map((condition) => ({
      ...condition,
      field_path: condition.field_path.trim(),
      excel_column_index: condition.source === "excel" ? (condition.excel_column_index ?? null) : null,
      excel_column_letter: condition.source === "excel" ? (condition.excel_column_letter?.trim() || null) : null,
      excel_header: condition.source === "excel" ? (condition.excel_header?.trim() || null) : null,
      value: condition.operator === "empty" || condition.operator === "not_empty" ? null : condition.value,
    })),
  });

  const openCreateDialog = () => {
    setEditingRule(null);
    fetchedSectionsRef.current.clear();
    setForm({
      ...emptyForm,
      profile_id: scope === "profile" && selectedProfileId ? selectedProfileId : null,
      actions: [{ ...emptyAction, section_id: activeSections[0]?.id ?? 0 }],
    });
    setDialogOpen(true);
  };

  const openEditDialog = (rule: RoutesAPI.RouteSelectionRule) => {
    setEditingRule(rule);
    fetchedSectionsRef.current.clear();
    setForm({
      code: rule.code,
      name: rule.name,
      profile_id: rule.profile_id,
      priority: rule.priority,
      is_active: rule.is_active,
      phase: rule.phase,
      conditions: rule.conditions.map((condition) => ({ ...condition })),
      actions: rule.actions.map((action) => ({
        action: action.action,
        section_id: action.section_id,
        operation_code: action.operation_code,
        path: action.path,
        value: action.value,
      })),
    });
    setDialogOpen(true);
  };

  const validateForm = () => {
    const normalized = normalizeForm(form);
    if (!normalized.name) return "Название обязательно";
    if (!Number.isFinite(normalized.priority)) return "Приоритет обязателен";
    if (!normalized.actions.length) return "Добавьте хотя бы одно действие";

    for (const action of normalized.actions) {
      if (isDslAction(action.action)) {
        if (!action.path?.startsWith("ctx.")) return "DSL действие: путь должен начинаться с 'ctx.'";
      } else if (isSectionAction(action.action)) {
        if (!action.section_id) return "В каждом действии по участкам должен быть выбран участок";
      }
    }

    for (const condition of normalized.conditions) {
      if (condition.source === "excel") {
        if (scope !== "profile") return "Excel-условия доступны только в группе правил";
        if (!selectedProfile) return "Для Excel-условий выберите группу";
        if (!(selectedProfile.excel_column_passport?.length ?? 0)) return "Сначала задайте паспорт колонок в группе правил";
        if (!condition.field_path && !condition.excel_column_index && !condition.excel_header) return "В каждом excel-условии нужно указать колонку";
      } else if (condition.source === "ctx") {
        if (!condition.field_path) return "В каждом ctx-условии должно быть поле";
      } else if (!condition.field_path) {
        return "В каждом условии должно быть поле";
      }
      if (!["empty", "not_empty"].includes(condition.operator) && (condition.value === null || String(condition.value ?? "").trim() === "")) {
        return "В условиях с выбранным оператором нужно значение";
      }
    }
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
      await loadRules();
    } catch (e) {
      toast({ variant: "destructive", title: "Ошибка сохранения правила", description: getErrorMessage(e) });
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (rule: RoutesAPI.RouteSelectionRule) => {
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

  const applyValuePreset = (index: number, value: unknown) => {
    updateCondition(index, { value });
  };

  const applyExcelColumn = (index: number, columnIndex: number) => {
    const column = ruleExcelColumns.find((item) => item.index === columnIndex);
    if (!column) return;
    updateCondition(index, {
      field_path: column.field_path,
      excel_column_index: column.index,
      excel_column_letter: column.letter,
      excel_header: column.header,
    });
  };

  const openProfileCreate = () => {
    setEditingProfile(null);
    setProfileForm(emptyProfileForm);
    setProfileDialogOpen(true);
  };

  const openProfileEdit = (profile: RoutesAPI.RouteRuleProfile) => {
    setEditingProfile(profile);
    setProfileForm({
      code: profile.code,
      name: profile.name,
      priority: profile.priority,
      is_active: profile.is_active,
      import_template_id: profile.import_template_id,
      excel_column_passport: (profile.excel_column_passport ?? []).map((column) => ({
        index: column.index,
        letter: column.letter,
        header: column.header,
        field_path: column.field_path,
      })),
      excel_passport_meta: { ...(profile.excel_passport_meta ?? {}) },
    });
    setProfileDialogOpen(true);
  };

  const handleSyncPassportFromTemplate = () => {
    if (!profileForm.import_template_id) {
      toast({ variant: "destructive", title: "Сначала выберите шаблон импорта" });
      return;
    }
    const template = importTemplates.find((item) => item.id === profileForm.import_template_id);
    if (!template) {
      toast({ variant: "destructive", title: "Шаблон импорта не найден" });
      return;
    }
    const syncedPassport = buildPassportFromTemplateMapping(template.column_mapping);
    if (!syncedPassport.length) {
      toast({ variant: "destructive", title: "В шаблоне нет данных для синхронизации паспорта" });
      return;
    }
    setProfileForm((current) => ({
      ...current,
      excel_column_passport: syncedPassport,
      excel_passport_meta: {
        ...(current.excel_passport_meta ?? {}),
        import_template_id: current.import_template_id,
        synced_at: new Date().toISOString(),
        source: "import_template",
      },
    }));
    toast({ title: "Паспорт синхронизирован", description: `Колонок: ${syncedPassport.length}`, variant: "success" });
  };

  const handleProfileSave = async () => {
    if (!profileForm.code.trim() || !profileForm.name.trim()) {
      toast({ variant: "destructive", title: "Код и название обязательны" });
      return;
    }

    const payload: RoutesAPI.RouteRuleProfileInput = {
      code: profileForm.code.trim(),
      name: profileForm.name.trim(),
      priority: Number(profileForm.priority),
      is_active: profileForm.is_active,
      import_template_id: profileForm.import_template_id,
      excel_column_passport: profileForm.excel_column_passport.map((column) => ({
        index: Number(column.index),
        letter: String(column.letter).trim().toUpperCase(),
        header: String(column.header).trim(),
        field_path: String(column.field_path).trim(),
      })),
      excel_passport_meta: { ...(profileForm.excel_passport_meta ?? {}) },
    };

    setSavingProfile(true);
    try {
      if (editingProfile) {
        await RoutesAPI.updateRouteRuleProfile(editingProfile.id, payload);
        toast({ title: "Группа обновлена", variant: "success" });
      } else {
        await RoutesAPI.createRouteRuleProfile(payload);
        toast({ title: "Группа создана", variant: "success" });
      }
      setProfileDialogOpen(false);
      await loadData();
      await loadRules();
    } catch (e) {
      toast({ variant: "destructive", title: "Ошибка сохранения группы", description: getErrorMessage(e) });
    } finally {
      setSavingProfile(false);
    }
  };

  const handleProfileDelete = async (profile: RoutesAPI.RouteRuleProfile) => {
    setDeletingProfileId(profile.id);
    try {
      await RoutesAPI.deleteRouteRuleProfile(profile.id);
      toast({ title: "Группа удалена", variant: "success" });
      if (selectedProfileId === profile.id) {
        setScope("global");
        setSelectedProfileId(null);
      }
      await loadData();
      await loadRules();
    } catch (e) {
      toast({ variant: "destructive", title: "Ошибка удаления группы", description: getErrorMessage(e) });
    } finally {
      setDeletingProfileId(null);
    }
  };

  const sourceOptionsForCondition = (condition: RoutesAPI.RouteSelectionCondition): RuleSource[] => {
    const base = (Object.keys(sourceLabels) as RuleSource[]).filter((source) => source !== "excel" || scope === "profile");
    if (condition.source === "excel" && !base.includes("excel")) {
      return [...base, "excel"];
    }
    return base;
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <CardTitle>Правила выбора маршрута</CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">{rules.length} правил</p>
          </div>
          <Button
            size="sm"
            onClick={openCreateDialog}
            disabled={!activeSections.length || (scope === "profile" && !selectedProfileId)}
          >
            <Plus className="mr-1 h-4 w-4" />
            Создать правило
          </Button>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button
            onClick={() => { setScope("global"); setSelectedProfileId(null); }}
            className={`px-3 py-1 text-sm rounded-md border transition-colors ${scope === "global" ? "bg-primary text-primary-foreground border-primary" : "hover:bg-accent border-border"}`}
          >
            Глобальные
          </button>
          {profiles.map((profile) => (
            <span
              key={profile.id}
              className={`inline-flex items-center gap-0.5 px-3 py-1 text-sm rounded-md border transition-colors ${
                !profile.is_active
                  ? "opacity-60 border-border"
                  : scope === "profile" && selectedProfileId === profile.id
                    ? "bg-primary text-primary-foreground border-primary"
                    : "hover:bg-accent border-border"
              }`}
            >
              <button
                onClick={() => { if (profile.is_active) { setScope("profile"); setSelectedProfileId(profile.id); } }}
                className="flex-1 text-left"
                disabled={!profile.is_active}
              >
                {profile.name}
              </button>
              <button
                onClick={(event) => { event.stopPropagation(); openProfileEdit(profile); }}
                className="p-0.5 rounded hover:bg-black/10 transition-colors"
                title="Редактировать группу"
              >
                <Pencil className="h-3 w-3" />
              </button>
            </span>
          ))}
          <button
            onClick={openProfileCreate}
            className="inline-flex items-center gap-0.5 px-2 py-1 text-sm rounded-md border border-dashed hover:bg-accent transition-colors"
            title="Создать группу"
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
        </div>
      </CardHeader>

      <CardContent>
        <TableContainer className="rounded-md">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Название</TableHead>
                <TableHead>Действия</TableHead>
                <TableHead>Приоритет</TableHead>
                <TableHead>Условия</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rules.map((rule) => (
                <TableRow
                  key={rule.id}
                  className={`cursor-pointer hover:bg-muted/50 ${!rule.is_active ? "opacity-50" : ""}`}
                  onClick={() => openEditDialog(rule)}
                >
                  <TableCell>
                    <div className="font-medium">{rule.name}</div>
                    <div className="flex items-center gap-1 mt-1">
                      <Badge variant={rule.phase === "normalize" ? "secondary" : "default"} className="text-[10px] px-1 py-0">
                        {phaseLabels[rule.phase]}
                      </Badge>
                      {rule.code && <span className="text-xs text-muted-foreground">{rule.code}</span>}
                    </div>
                    {rule.profile_name && <div className="text-xs text-muted-foreground">Группа: {rule.profile_name}</div>}
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {rule.actions.map((action, index) => {
                        const isDsl = isDslAction(action.action);
                        const isSection = isSectionAction(action.action);
                        return (
                          <Badge key={`${rule.id}-${index}`} variant={isDsl ? "outline" : (action.action === "require_section" ? "default" : "secondary")}>
                            {actionLabels[action.action]} {isDsl ? (action.path ?? "") : isSection && action.operation_code ? `${action.section_code ?? action.section_id} → ${action.operation_code}` : (action.section_code ?? action.section_id)}
                          </Badge>
                        );
                      })}
                    </div>
                  </TableCell>
                  <TableCell className="font-medium">{rule.priority}</TableCell>
                  <TableCell>{rule.conditions.length || "Всегда"}</TableCell>
                </TableRow>
              ))}
              {!loading && rules.length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} className="py-6 text-center text-muted-foreground">Правил выбора маршрута нет</TableCell>
                </TableRow>
              )}
              {loading && (
                <TableRow>
                  <TableCell colSpan={4} className="py-6 text-center text-muted-foreground">Загрузка...</TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </CardContent>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="w-[min(980px,calc(100vw-2rem))] max-h-[90vh] flex flex-col">
          <DialogHeader>
            <DialogTitle>{editingRule ? "Редактировать правило" : "Создать правило"}</DialogTitle>
          </DialogHeader>

          <div className="grid gap-4 overflow-y-auto">
            <div className="grid gap-3 md:grid-cols-[1fr_1fr_120px_160px]">
              <label className="grid gap-1.5 text-sm font-medium">
                Название правила
                <Input value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} />
              </label>
              <label className="grid gap-1.5 text-sm font-medium">
                Код правила (опционально)
                <Input value={form.code ?? ""} onChange={(event) => setForm((current) => ({ ...current, code: event.target.value }))} placeholder="Опционально" />
              </label>
              <label className="grid gap-1.5 text-sm font-medium">
                Приоритет
                <Input type="number" value={form.priority} onChange={(event) => setForm((current) => ({ ...current, priority: Number(event.target.value) }))} />
              </label>
              <label className="grid gap-1.5 text-sm font-medium">
                Фаза
                <Select value={form.phase ?? "route_select"} onValueChange={(value) => setForm((current) => ({ ...current, phase: value as RulePhase }))}>
                  <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {(Object.keys(phaseLabels) as RulePhase[]).map((phase) => (
                      <SelectItem key={phase} value={phase}>{phaseLabels[phase]}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </label>
            </div>

            {scope === "profile" && (
              <div className={`rounded-md border p-3 text-xs ${passportStatusClassName(selectedProfilePassportStatus.level)}`}>
                <div className="font-medium">{selectedProfilePassportStatus.title}</div>
                <div className="mt-1">{selectedProfilePassportStatus.description}</div>
              </div>
            )}

            <div className="max-h-[40vh] overflow-y-auto pr-1 space-y-3">
              {/* Conditions */}
              <div className="grid gap-2">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold">Условия</h3>
                  <Button size="sm" variant="outline" onClick={() => setForm((current) => ({ ...current, conditions: [...current.conditions, { ...emptyCondition }] }))}>
                    <Plus className="mr-1 h-4 w-4" />
                    Добавить условие
                  </Button>
                </div>

                {form.conditions.length > 0 ? (
                  <div className="rounded-md border overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead className="border-b bg-muted/50">
                        <tr>
                          <th className="text-left py-1 px-2 font-medium">Источник</th>
                          <th className="text-left py-1 px-2 font-medium">Поле / колонка</th>
                          <th className="text-left py-1 px-2 font-medium">Оператор</th>
                          <th className="text-left py-1 px-2 font-medium">Значение</th>
                          <th className="text-center py-1 px-2 font-medium">Aa</th>
                          <th className="py-1 px-2 w-12" />
                        </tr>
                      </thead>
                      <tbody>
                        {form.conditions.map((condition, index) => (
                          <ConditionRow
                            key={`${condition.source}-${index}`}
                            index={index}
                            condition={condition}
                            scope={scope}
                            ruleExcelColumns={ruleExcelColumns}
                            fieldOptionsBySource={fieldOptionsBySource}
                            valuePresets={valuePresets}
                            sourceOptionsForCondition={sourceOptionsForCondition}
                            onUpdateCondition={updateCondition}
                            onApplyExcelColumn={applyExcelColumn}
                            onApplyValuePreset={applyValuePreset}
                            onRemoveCondition={(conditionIndex) => setForm((current) => ({
                              ...current,
                              conditions: current.conditions.filter((_, idx) => idx !== conditionIndex),
                            }))}
                          />
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}

              {form.conditions.length === 0 && <div className="rounded-md border p-3 text-sm text-muted-foreground">Правило будет применяться всегда.</div>}
              </div>

              {/* Actions */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-sm font-semibold">
                    {form.phase === "normalize" ? "DSL-действия" : "Действия по участкам"}
                  </h3>
                  <Button size="sm" variant="outline" onClick={() => {
                    if (form.phase === "normalize") {
                      setForm((current) => ({ ...current, actions: [...current.actions, { ...emptyDslAction }] }));
                    } else {
                      setForm((current) => ({ ...current, actions: [...current.actions, { ...emptyAction, section_id: activeSections[0]?.id ?? 0 }] }));
                    }
                  }}>
                    <Plus className="mr-1 h-4 w-4" />
                    Добавить действие
                  </Button>
                </div>

                <div className="rounded-md border overflow-hidden">
                  <table className="w-full text-xs">
                    <thead className="border-b bg-muted/50">
                      <tr>
                        <th className="text-left py-1 px-2 text-xs font-medium">Действие</th>
                        {form.phase === "normalize" ? (
                          <>
                            <th className="text-left py-1 px-2 text-xs font-medium">Путь (ctx.*)</th>
                            <th className="text-left py-1 px-2 text-xs font-medium">Значение (JSON)</th>
                          </>
                        ) : (
                          <>
                            <th className="text-left py-1 px-2 text-xs font-medium">Участок</th>
                            <th className="text-left py-1 px-2 text-xs font-medium">Операция</th>
                          </>
                        )}
                        <th className="py-1 px-1 w-8"></th>
                      </tr>
                    </thead>
                    <tbody>
                      {form.actions.length === 0 ? (
                        <tr>
                          <td colSpan={4} className="py-3 text-center text-muted-foreground text-xs">
                            Нет действий. Добавьте хотя бы одно.
                          </td>
                        </tr>
                      ) : (
                        form.actions.map((action, index) => {
                          const dsl = isDslAction(action.action);
                          return (
                          <tr key={index} className="border-b last:border-b-0">
                            <td className="py-0.5 px-2">
                              <Select value={action.action} onValueChange={(value) => {
                                const newAction = value as RoutesAPI.RouteSelectionAction["action"];
                                if (isDslAction(newAction)) {
                                  updateAction(index, { action: newAction, section_id: null, path: action.path ?? "ctx.", value: action.value ?? null });
                                } else {
                                  updateAction(index, { action: newAction, path: null, value: null, section_id: action.section_id ?? 0 });
                                }
                              }}>
                                <SelectTrigger className="h-6 text-xs">
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                  {(Object.keys(actionLabels) as RoutesAPI.RouteSelectionAction["action"][]).map((value) => (
                                    <SelectItem key={value} value={value}>{actionLabels[value]}</SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                            </td>
                            {dsl ? (
                              <>
                                <td className="py-0.5 px-2">
                                  <Input
                                    value={action.path ?? "ctx."}
                                    onChange={(e) => updateAction(index, { path: e.target.value })}
                                    placeholder="ctx.field"
                                    className="h-6 text-xs"
                                  />
                                </td>
                                <td className="py-0.5 px-2">
                                  <Input
                                    value={JSON.stringify(action.value ?? "")}
                                    onChange={(e) => {
                                      try {
                                        const parsed = e.target.value === "" ? null : JSON.parse(e.target.value);
                                        updateAction(index, { value: parsed });
                                      } catch {
                                        // Invalid JSON, ignore
                                      }
                                    }}
                                    placeholder='null, "text", 42, [1,2]'
                                    className="h-6 text-xs"
                                  />
                                </td>
                              </>
                            ) : isSectionAction(action.action) ? (
                              <>
                                <td className="py-0.5 px-2">
                                  <SectionSelect
                                    sections={sections}
                                    value={action.section_id ?? 0}
                                    onValueChange={(value) => {
                                      updateAction(index, { section_id: value });
                                      fetchSectionOperations(value);
                                    }}
                                    className="h-6 text-xs"
                                  />
                                </td>
                                <td className="py-0.5 px-2">
                                  <Select
                                    value={action.operation_code ?? "__none__"}
                                    onValueChange={(value) => updateAction(index, { operation_code: value === "__none__" ? null : value })}
                                    disabled={!action.section_id}
                                  >
                                    <SelectTrigger className="h-6 text-xs">
                                      <SelectValue placeholder="Выберите операцию" />
                                    </SelectTrigger>
                                    <SelectContent>
                                      <SelectItem value="__none__">—</SelectItem>
                                      {(sectionOps[action.section_id ?? 0] ?? []).map((op) => (
                                        <SelectItem key={op.operation_code} value={op.operation_code}>
                                          {op.operation_name} ({op.operation_code})
                                        </SelectItem>
                                      ))}
                                      {(!action.section_id || !(sectionOps[action.section_id ?? 0]?.length)) && (
                                        <SelectItem value="__empty__" disabled>
                                          {!action.section_id ? "Сначала выберите участок" : "Нет операций"}
                                        </SelectItem>
                                      )}
                                    </SelectContent>
                                  </Select>
                                </td>
                              </>
                            ) : (
                              <td className="py-0.5 px-2">
                                <SectionSelect
                                  sections={sections}
                                  value={action.section_id ?? 0}
                                  onValueChange={(value) => updateAction(index, { section_id: value })}
                                  className="h-6 text-xs"
                                />
                              </td>
                            )}
                            <td className="py-0.5 px-1 w-8">
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-5 w-5 p-0 text-red-600"
                                onClick={() => setForm((current) => ({ ...current, actions: current.actions.filter((_, idx) => idx !== index) }))}
                              >
                                <Trash2 className="h-3 w-3" />
                              </Button>
                            </td>
                          </tr>
                          );
                        })
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </div>

          <DialogFooter className="flex items-center justify-between w-full sm:justify-between">
            <div>
              {editingRule && (
                <Button variant="destructive" onClick={() => void handleDelete(editingRule)} disabled={deletingRuleId === editingRule.id || saving}>
                  <Trash2 className="mr-1 h-4 w-4" />
                  Удалить
                </Button>
              )}
            </div>
            <div className="flex gap-2 items-center">
              <Checkbox checked={form.is_active} onCheckedChange={(checked) => setForm((current) => ({ ...current, is_active: checked === true }))} />
              <label className="text-sm">Активно</label>
              <Button variant="outline" onClick={() => setDialogOpen(false)} disabled={saving}>Отмена</Button>
              <Button onClick={() => void handleSave()} disabled={saving}>{saving ? "Сохранение..." : "Сохранить"}</Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={profileDialogOpen} onOpenChange={(open) => {
        if (!open) {
          setEditingProfile(null);
          setProfileForm(emptyProfileForm);
        }
        setProfileDialogOpen(open);
      }}>
        <DialogContent className="w-[min(700px,calc(100vw-2rem))] max-h-[92vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editingProfile ? "Редактировать группу" : "Новая группа"}</DialogTitle>
          </DialogHeader>

          <div className="flex flex-wrap gap-4">
            <div className="w-[250px]">
              <label className="text-sm font-medium">Название</label>
              <Input value={profileForm.name} onChange={(event) => setProfileForm((current) => ({ ...current, name: event.target.value }))} />
            </div>
            <div className="w-[250px]">
              <label className="text-sm font-medium">Код</label>
              <Input value={profileForm.code} onChange={(event) => setProfileForm((current) => ({ ...current, code: event.target.value }))} />
            </div>
            <div className="w-[100px]">
              <label className="text-sm font-medium">Приоритет</label>
              <Input type="number" value={profileForm.priority} onChange={(event) => setProfileForm((current) => ({ ...current, priority: Number(event.target.value) }))} />
            </div>
          </div>

          <div className="grid gap-2">
            <div className="flex items-end gap-2">
              <div className="w-[320px]">
                <label className="text-sm font-medium">Шаблон импорта</label>
                <Select
                  value={profileForm.import_template_id ? String(profileForm.import_template_id) : "__none__"}
                  onValueChange={(value) => setProfileForm((current) => ({
                    ...current,
                    import_template_id: value === "__none__" ? null : Number(value),
                  }))}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Выберите шаблон импорта" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__none__">Не выбран</SelectItem>
                    {importTemplates.map((t) => (
                      <SelectItem key={t.id} value={String(t.id)}>{t.name}{t.code ? ` (${t.code})` : ""}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <Button type="button" variant="outline" size="sm" onClick={handleSyncPassportFromTemplate}>
                Применить
              </Button>
            </div>
            <span className="text-xs text-muted-foreground">Ручная синхронизация без автозамены при смене шаблона</span>
            <div className={`rounded-md border p-3 text-xs ${passportStatusClassName(profileFormPassportStatus.level)}`}>
              <div className="font-medium">{profileFormPassportStatus.title}</div>
              <div className="mt-1">{profileFormPassportStatus.description}</div>
            </div>
          </div>

          <DialogFooter className="flex items-center justify-between w-full sm:justify-between">
            <div>
              {editingProfile && (
                <Button variant="destructive" onClick={() => void handleProfileDelete(editingProfile)} disabled={deletingProfileId === editingProfile.id || savingProfile}>
                  <Trash2 className="mr-1 h-4 w-4" />
                  Удалить
                </Button>
              )}
            </div>
            <div className="flex items-center gap-2">
              <Checkbox checked={profileForm.is_active} onCheckedChange={(checked) => setProfileForm((current) => ({ ...current, is_active: checked === true }))} />
              <label className="text-sm">Активен</label>
              <Button variant="outline" onClick={() => { setProfileDialogOpen(false); }} disabled={savingProfile}>
                Отмена
              </Button>
              <Button onClick={() => void handleProfileSave()} disabled={savingProfile}>
                {savingProfile ? "Сохранение..." : "Сохранить"}
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
