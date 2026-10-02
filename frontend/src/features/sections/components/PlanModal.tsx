/**
 * Окно плана участка.
 *
 * Печать настраивается по участку: базовый пресет окна — профиль печати
 * участка (`PRINT_PROFILES` по коду секции). При открытии применяется пресет
 * прошлого выбора, если он совпал с одним из пресетов участка, иначе — базовый
 * набор участка; набор без пресета профиль участка не перекрывает. Набор
 * колонок — единственный источник правды и для листа, и для кнопок «Колонки
 * печати» (ADR-0042).
 *
 * Для анодирования показывается единое дерево: предоперации, анодирование и
 * упаковка остаются в строке одного задания. Лист печатается сразу из окна:
 * набор колонок и заголовок задаются в его шапке, печатаются все задания.
 */

import { useEffect, useState } from "react";
import { Printer } from "lucide-react";
import type { SectionBoardTask, SectionOperation } from "@/shared/api/shopfloor";
import { PlanTaskTable } from "./PlanTaskTable";
import type { PlanTaskGroupingMode } from "../lib/planTaskGroups";
import {
  addPreset,
  deletePreset,
  findMatchingPresetId,
  isSameSettings,
  loadPresets,
  sectionBasePreset,
  type PlanPreset,
} from "../lib/planPresets";
import {
  PACKAGING_ONLY_COLUMNS,
  PLAN_COLUMNS,
  PRINTABLE_COLUMNS,
  normalizePrintSettings,
  type PlanColumnKey,
  type PrintSettings,
} from "../lib/planPrintSettings";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  Input,
  PRINT_SHEET_WIDTH_CLASS,
  PrintStyles,
} from "@/shared/ui";
import { DIALOG_SIZES } from "@/shared/lib/dialogSizes";
import { cn } from "@/shared/utils/cn";

interface PlanModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sectionId: number;
  sectionName: string;
  /** Код секции задаёт печатный профиль по умолчанию. */
  sectionCode?: string | null;
  /**
   * Есть ли у участка упаковочные операции (`Section.has_packaging`). Лист
   * печати транслирует доску: на участке без упаковки колонки нет ни в
   * наборе, ни в кнопках.
   */
  hasPackaging?: boolean;
  tasks: SectionBoardTask[];
  availableOperations?: SectionOperation[];
}

/**
 * Настройки окна на открытии: набор прошлого выбора, если он совпадает с
 * одним из пресетов участка, иначе — базовый пресет участка. Набор, не
 * совпавший ни с чем (старая версия приложения, ручная правка колонок),
 * профиль участка молча не перекрывает: мастер видит ровно тот пресет,
 * который подсвечен активным.
 */
function loadPrintSettings(
  sectionId: number,
  presets: PlanPreset[],
  baseSettings: PrintSettings,
): PrintSettings {
  const stored = readStoredSettings(sectionId);
  return stored && findMatchingPresetId(presets, stored) ? stored : baseSettings;
}

function readStoredSettings(sectionId: number): PrintSettings | null {
  try {
    const raw = localStorage.getItem(`plan-print-settings-${sectionId}`);
    if (!raw) return null;
    const settings = normalizePrintSettings(JSON.parse(raw) as Partial<PrintSettings>, []);
    return settings.columns.length > 0 ? settings : null;
  } catch {
    return null;
  }
}

function savePrintSettings(sectionId: number, settings: PrintSettings) {
  localStorage.setItem(`plan-print-settings-${sectionId}`, JSON.stringify(settings));
}

/** Группировка печатного листа всегда по артикулу и размеру. */
const GROUPING_MODE: PlanTaskGroupingMode = "article";

/**
 * Подсказка пресета — его набор колонок по заголовкам «Колонок печати».
 * Базовый пресет участка иначе не отличить от остальных: набор у него свой
 * для каждого участка, а имя одно.
 */
function presetColumnTitles(preset: PlanPreset): string {
  return preset.settings.columns
    .map((key) => PLAN_COLUMNS.find((column) => column.key === key)?.title ?? key)
    .join(" · ");
}

export function PlanModal({
  open,
  onOpenChange,
  sectionId,
  sectionName,
  sectionCode,
  hasPackaging,
  tasks,
}: PlanModalProps) {
  /**
   * Колонки, которых у участка не бывает. Флаг не пришёл (`undefined` —
   * старый кэш, ошибка справочника) — не скрываем ничего: ошибка справочника
   * не должна прятать данные.
   */
  const unavailableColumns: readonly PlanColumnKey[] =
    hasPackaging === false ? PACKAGING_ONLY_COLUMNS : [];

  // Настройки окна на открытии: базовый пресет участка либо названный пресет
  // прошлого выбора (см. `loadPrintSettings`). Порядок состояний важен: набор
  // настроек выбирается по уже загруженному списку пресетов.
  const [presets, setPresets] = useState<PlanPreset[]>(() =>
    loadPresets(sectionId, sectionCode, unavailableColumns),
  );
  const [printSettings, setPrintSettings] = useState<PrintSettings>(() =>
    loadPrintSettings(
      sectionId,
      presets,
      sectionBasePreset(sectionCode, unavailableColumns).settings,
    ),
  );
  const [hiddenGroupKeys, setHiddenGroupKeys] = useState<Set<string>>(() => new Set());
  const [activePresetId, setActivePresetId] = useState<string | null>(null);
  const [newPresetName, setNewPresetName] = useState("");
  const [presetToDelete, setPresetToDelete] = useState<PlanPreset | null>(null);

  useEffect(() => {
    const nextPresets = loadPresets(sectionId, sectionCode, unavailableColumns);
    setPresets(nextPresets);
    setPrintSettings(
      loadPrintSettings(
        sectionId,
        nextPresets,
        sectionBasePreset(sectionCode, unavailableColumns).settings,
      ),
    );
    setActivePresetId(null);
    setHiddenGroupKeys(new Set());
    // `unavailableColumns` выводится из `hasPackaging` — он и в зависимостях.
  }, [sectionId, sectionCode, hasPackaging]);

  useEffect(() => {
    // Пишем только названный набор: набор без пресета при следующем открытии
    // всё равно уступает базовому пресету участка, и хранить его незачем.
    if (findMatchingPresetId(presets, printSettings)) {
      savePrintSettings(sectionId, printSettings);
    }
  }, [sectionId, printSettings, presets]);

  useEffect(() => {
    const activePreset = presets.find((preset) => preset.id === activePresetId);
    if (activePresetId && !activePreset) {
      setActivePresetId(null);
    } else if (activePreset && !isSameSettings(activePreset.settings, printSettings)) {
      setActivePresetId(null);
    } else if (activePresetId === null) {
      const match = findMatchingPresetId(presets, printSettings);
      if (match) setActivePresetId(match);
    }
  }, [printSettings, presets, activePresetId]);

  const hideGroup = (key: string) => {
    setHiddenGroupKeys((previous) => new Set(previous).add(key));
  };

  /** Переключение колонки в порядке определения — печать рендерит ровно выбранные. */
  const toggleColumn = (column: PlanColumnKey) => {
    setPrintSettings((previous) => {
      const next = new Set(previous.columns);
      if (next.has(column)) {
        if (next.size === 1) return previous; // хотя бы одна колонка нужна
        next.delete(column);
      } else {
        next.add(column);
      }
      return {
        ...previous,
        columns: PLAN_COLUMNS.map((def) => def.key).filter((key) => next.has(key)),
      };
    });
  };

  const applyPreset = (preset: PlanPreset) => {
    // Набор пресета уже приведён к применимым колонкам участка (`loadPresets`):
    // второго места, где список колонок режется, быть не должно.
    setPrintSettings({ ...preset.settings });
    setActivePresetId(preset.id);
  };

  const handleSavePreset = () => {
    const name = newPresetName.trim();
    if (!name) return;
    const created = addPreset(sectionId, name, printSettings);
    setPresets(loadPresets(sectionId, sectionCode, unavailableColumns));
    setActivePresetId(created.id);
    setNewPresetName("");
  };

  const confirmDeletePreset = () => {
    if (!presetToDelete) return;
    deletePreset(sectionId, presetToDelete.id);
    setPresets(loadPresets(sectionId, sectionCode, unavailableColumns));
    if (activePresetId === presetToDelete.id) setActivePresetId(null);
    setPresetToDelete(null);
  };

  const sheetTitle =
    printSettings.title ||
    `План: ${sectionName} от ${new Date().toLocaleDateString("ru-RU")}`;

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
      <PrintStyles />
      <DialogContent
        className={cn(
          DIALOG_SIZES.wide.width,
          DIALOG_SIZES.wide.height,
          "flex flex-col gap-0 overflow-hidden p-0",
          "bg-white print-area",
        )}
      >
        <DialogHeader className="p-4 border-b space-y-3 no-print text-left">
          <DialogTitle className="text-lg font-semibold">План: {sectionName}</DialogTitle>
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <span className="font-medium text-muted-foreground">Пресеты:</span>
            {presets.map((preset) => (
              <div key={preset.id} className="relative group">
                <Button
                  type="button"
                  size="sm"
                  variant={activePresetId === preset.id ? "default" : "outline"}
                  title={presetColumnTitles(preset)}
                  onClick={() => applyPreset(preset)}
                >
                  {preset.isBuiltin ? `★ ${preset.name}` : preset.name}
                </Button>
                {!preset.isBuiltin && (
                  <button type="button" onClick={() => setPresetToDelete(preset)} className="absolute -top-1.5 -right-1.5 hidden group-hover:flex items-center justify-center h-4 w-4 rounded-full bg-red-500 text-white text-[10px]" title="Удалить пресет">×</button>
                )}
              </div>
            ))}
            <div className="flex items-center gap-1 ml-1">
              <Input value={newPresetName} onChange={(event) => setNewPresetName(event.target.value)} onKeyDown={(event) => event.key === "Enter" && handleSavePreset()} placeholder="Название пресета" className="h-9 w-36 text-xs" />
              <Button type="button" size="sm" variant="secondary" onClick={handleSavePreset} disabled={!newPresetName.trim()}>Сохранить</Button>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <span className="font-medium text-muted-foreground">Колонки печати:</span>
            {PRINTABLE_COLUMNS.filter(
              (column) => !unavailableColumns.includes(column.key),
            ).map((column) => (
              <Button key={column.key} type="button" size="sm" variant={printSettings.columns.includes(column.key) ? "default" : "outline"} onClick={() => toggleColumn(column.key)}>
                {column.title}
              </Button>
            ))}
          </div>
        </DialogHeader>

        <div className="flex-1 overflow-auto p-4 print-sheet">
          <div className={PRINT_SHEET_WIDTH_CLASS}>
            <div className="mb-4 text-center">
              <div className="text-sm font-bold uppercase tracking-wide">{sheetTitle}</div>
              <div className="mt-0.5 text-[10px] text-muted-foreground">
                Сформировано: {new Date().toLocaleString("ru-RU")}
              </div>
            </div>
            {hiddenGroupKeys.size > 0 && (
              <div className="no-print mb-3 flex items-center gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                Скрыто групп: <b>{hiddenGroupKeys.size}</b>
                <Button type="button" size="sm" variant="outline" className="ml-auto" onClick={() => setHiddenGroupKeys(new Set())}>Показать все</Button>
              </div>
            )}
            <PlanTaskTable tasks={tasks} mode={GROUPING_MODE} hiddenGroupKeys={hiddenGroupKeys} onHideGroup={hideGroup} columns={printSettings.columns} />
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 border-t p-4 no-print">
          <Button type="button" size="sm" variant="ghost" onClick={() => onOpenChange(false)}>
            Закрыть
          </Button>
          <Button type="button" size="sm" className="gap-2 px-6" onClick={() => window.print()}>
            <Printer className="h-4 w-4" />
            Печать
          </Button>
        </div>
      </DialogContent>
    </Dialog>
    <AlertDialog open={!!presetToDelete} onOpenChange={(isOpen) => !isOpen && setPresetToDelete(null)}>
      <AlertDialogContent className="max-w-sm">
        <AlertDialogHeader><AlertDialogTitle>Удалить пресет?</AlertDialogTitle><AlertDialogDescription>Пресет «{presetToDelete?.name}» будет удалён.</AlertDialogDescription></AlertDialogHeader>
        <AlertDialogFooter><AlertDialogCancel>Отмена</AlertDialogCancel><AlertDialogAction onClick={confirmDeletePreset} className="bg-destructive text-destructive-foreground">Удалить</AlertDialogAction></AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
    </>
  );
}
