import { useCallback, useEffect, useMemo, useState, useRef } from "react";
import { keepPreviousData, useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";


import { apiClient, getErrorMessage } from "@/shared/api/client";
import type { UserRole } from "@/features/auth/api";
import { listSections } from "@/shared/api/sections";
import {
  bulkCompleteTasks,
  completeTask,
  createDailyPlan,
  getDailyPlanComposition,
  getSectionBoard,
  getSectionBoardColumnValues,
  getSectionDailyStats,
  getSectionsSummary,
  listDailyPlans,
  revokeDailyPlanItem,
  type CreateDailyPlanInput,
  type DailyStatsRow,
  type SectionBoardTask,
  type SectionBoardResponse,
  type TaskGroup,
  type ShortageStrategy,
  type BulkCompleteEntry,
  type DailyPlanCompositionItem,
} from "@/shared/api/shopfloor";
import { invalidateAfter } from "@/shared/api/cacheInvalidation";
import { operationalPollingOptions } from "@/shared/api/operationalPolling";
import { queryKeys } from "@/shared/api/queryKeys";
import { usePaginatedTableQuery } from "@/shared/hooks/usePaginatedTableQuery";
import type { SectionBoardQueryParams } from "@/shared/api/shopfloor";
import { isFirstRowsLoad, keepPreviousDataForScope } from "@/shared/lib/tableQueryPlaceholder";
import { DateRangePicker, renderIcon, toast, type DateRangeValue } from "@/shared/ui";
import { useBulkSelection } from "@/shared/bulk";
import { BulkResultsDialog, summarizeBulkResults, type BulkActionResultItem, type BulkActionSummary } from "@/shared/bulk";
import { isProductionSection } from "@/shared/lib/sectionTypes";
import { SectionSwitcherTiles } from "../components/SectionSwitcherTiles";
import { SectionTasksBoard, type TaskActionDialogType, type TaskBoardViewMode } from "../components/SectionTasksBoard";
import { TaskActionDrawer } from "../components/TaskActionDrawer";
import { BulkCompleteFooter } from "../components/BulkCompleteFooter";
import { BulkDraftExitDialog } from "../components/BulkDraftExitDialog";
import { resolveFactQuantity } from "../lib/factQuantity";
import {
  draftEntries,
  draftShortage,
  draftTotals,
  isDraftEmpty,
  withoutDraftIds,
  type BulkDraft,
} from "../lib/bulkDraft";
import { DailyPlansPanel } from "../components/DailyPlansPanel";
import { PlanPrintButton } from "../components/PlanPrintButton";
import { getDailyPlanCreationCandidates, mergeDailyPlanTasks } from "../lib/dailyPlans";
import { PlanModal } from "../components/PlanModal";
import { SectionStockBalances } from "../components/SectionStockBalances";
import {
  SectionPanelToggles,
  isBalancesPanelVisible,
  isPlanPanelVisible,
  isTasksPanelVisible,
  type SectionContentMode,
} from "../components/SectionPanelToggles";
import { PRESET_PROFILES, type GroupingProfile } from "../lib/groupingProfiles";
import {
  BOARD_SERVER_VALUE_FIELDS,
  buildBoardColumnValuesParams,
  type TaskSortField,
} from "../lib/boardQueryParams";
import { boardColumns } from "../lib/boardColumns";
import {
  getCompletionBlockReason,
  groupTasksByBlockReason,
  isTaskCompletable,
} from "../lib/taskStatus";
import { actionReasonText, type ActionReasonCode } from "@/shared/lib/actionReasons";
import { createAuditLog, getAuditLogs, type AuditLogEntry } from "@/shared/api/auditLogs";
import { isAnyDialogOpen } from "@/shared/lib/dialogOpen";
import { cn } from "@/shared/utils/cn";
import { fmtQty, toQtyInteger } from "@/shared/lib/quantityFormat";

/**
 * Набор фильтров доски, который страница держит для запроса. Один пустой объект
 * на модуль, а не литерал в теле компонента: он попадает в `resetPageDeps` и в
 * зависимости `useMemo`, где важна идентичность (ADR-0060 п.4).
 */
type BoardServerQuery = Pick<
  SectionBoardQueryParams,
  "search" | "product_sku" | "dimensions" | "sort"
>;
const EMPTY_SERVER_QUERY: BoardServerQuery = {};

type MeResponse = {
  id: number;
  email: string;
  full_name: string;
  role: UserRole;
  section_id: number | null;
  is_active: boolean;
};


function nowLocalDateTime(): string {
  const d = new Date();
  const p = (v: number) => String(v).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

function nowLocalDateTimeParts(): { date: string; time: string } {
  const d = new Date();
  const p = (v: number) => String(v).padStart(2, "0");
  return {
    date: `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`,
    time: `${p(d.getHours())}:${p(d.getMinutes())}`,
  };
}

function makeIdempotencyKey(prefix: string): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1_000_000)}`;
}

function conflictHintFromError(message: string): string | null {
  const normalized = message.toLowerCase();
  if (normalized.includes("exceeds available")) return "Количество больше доступного для выдачи. Проверьте поле 'Доступно'.";
  if (normalized.includes("exceeds quantity in work")) return "Количество факта больше объема 'В работе'. Сначала уменьшите факт или довыдайте в работу.";
  if (normalized.includes("exceeds transferable")) return "Количество передачи больше доступного к передаче. Проверьте 'Факт - Передано'.";
  if (normalized.includes("must be sent")) return "Передача уже обработана. Обновите список входящих передач.";
  if (normalized.includes("accepted + rejected exceeds sent")) return "Сумма принятого и отклоненного превышает отправленное количество.";
  if (normalized.includes("next route step")) return "Передавать можно только на следующий этап маршрута.";
  if (normalized.includes("locked to single-window context")) return "Режим одного окна разрешает работу только с текущим участком.";
  return null;
}

export function SectionsTasksPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const params = useParams<{ sectionId?: string }>();
  const [searchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const isSingleWindow = searchParams.get("singleWindow") === "1";
  const requestedSectionId = params.sectionId ? Number(params.sectionId) : null;
  const isRequestedSectionIdValid = Number.isFinite(requestedSectionId);
  const lockedSectionId = isSingleWindow && isRequestedSectionIdValid ? (requestedSectionId as number) : null;

  const [sectionId, setSectionId] = useState<number | null>(
    params.sectionId && Number.isFinite(Number(params.sectionId)) ? Number(params.sectionId) : null
  );
  // Состояние участка живёт в URL, но может бежать впереди него: плитка
  // переключает участок локально, а `navigate` в data-router коммитит location
  // в transition — сразу после клика `params.sectionId` ещё прежний. Параметр
  // переносим в состояние только когда он сам сменился, иначе синхронизация
  // откатывала бы участок назад и доска мигала бы «прежний ↔ новый».
  const urlSectionIdRef = useRef<number | null>(
    params.sectionId && Number.isFinite(Number(params.sectionId)) ? Number(params.sectionId) : null
  );
  const profile = PRESET_PROFILES.find((p) => p.id === "sku+routeHistoryAfter") || PRESET_PROFILES[2];

  // По умолчанию доска показывает активные и ожидающие задания: ожидающие —
  // отдельным блоком внизу таблицы, под разделителем «В ожидании».
  const [viewMode, setViewMode] = useState<TaskBoardViewMode>({ active: true, waiting: true, completed: false });
  const [sectionContentMode, setSectionContentMode] = useState<SectionContentMode>("tasks");
  const [creatingDailyPlan, setCreatingDailyPlan] = useState(false);
  const [dateRange, setDateRange] = useState<DateRangeValue>({ from: "", to: "" });
  const dateFrom = dateRange.from;
  const dateTo = dateRange.to;
  const [conflictHint, setConflictHint] = useState<string | null>(null);

  const { data: me } = useQuery({
    queryKey: queryKeys.auth.me(),
    queryFn: async () => (await apiClient.get<MeResponse>("/auth/me")).data,
    retry: false,
  });


  const [actionDialog, setActionDialog] = useState<{
    open: boolean;
    type: TaskActionDialogType;
    task: SectionBoardTask | null;
  }>({
    open: false,
    type: "complete",
    task: null,
  });
  const [actionQty, setActionQty] = useState("");
  const [defectQty, setDefectQty] = useState("");
  const [performedDate, setPerformedDate] = useState("");
  const [performedShift, setPerformedShift] = useState<"1" | "2">("1");
  const [actionComment, setActionComment] = useState("");
  const [shortageStrategy, setShortageStrategy] = useState<ShortageStrategy>("fail");
  const [planModalOpen, setPlanModalOpen] = useState(false);
  const [selectedPlanIds, setSelectedPlanIds] = useState<Set<number>>(new Set());

  // Bulk mode state. Mass operations stay in the current page and do not
  // activate single-window/fullscreen navigation.
  const [bulkMode, setBulkMode] = useState(searchParams.get("bulk") === "1");
  // Массовый ввод факта (#283): черновик привязан к id задачи и живёт здесь,
  // поэтому смена фильтра и сортировки не двигает введённое у своих заданий.
  // Панели массовых операций больше нет: ввод идёт в строках доски, а итог и
  // подтверждение показывает футер.
  const [bulkDraft, setBulkDraft] = useState<BulkDraft>({});
  const [bulkPerformedDate, setBulkPerformedDate] = useState(() => nowLocalDateTimeParts().date);
  const [bulkPerformedShift, setBulkPerformedShift] = useState<"1" | "2">("1");
  const [bulkComment, setBulkComment] = useState("");
  const [bulkShortageStrategy, setBulkShortageStrategy] = useState<ShortageStrategy | null>(null);
  // Строки, отрисованные доской: по ним футер считает «вне текущего фильтра».
  const [visibleTaskIds, setVisibleTaskIds] = useState<ReadonlySet<number>>(() => new Set());
  // Выход с непустым черновиком спрашивает подтверждение: действие держим до
  // ответа оператора, чтобы Escape, тумблер режима и смена участка не теряли
  // набранное молча.
  const [draftExitAction, setDraftExitAction] = useState<(() => void) | null>(null);
  const [bulkResults, setBulkResults] = useState<BulkActionResultItem<number>[]>([]);
  const [bulkResultsOpen, setBulkResultsOpen] = useState(false);
  const [bulkSummary, setBulkSummary] = useState<BulkActionSummary | null>(null);
  const revokeSelection = useBulkSelection<number>();
  useEffect(() => {
    setSelectedPlanIds(new Set());
    setCreatingDailyPlan(false);
    revokeSelection.clear();
    bulkSelection.clear();
    setBulkDraft({});
    setBulkShortageStrategy(null);
  }, [sectionId]);
  const bulkSelection = useBulkSelection<number>();
  // Снятая строка уносит и своё введённое количество: черновик не хранит
  // значения задач, которых нет в выделении, иначе окно выхода и счётчики
  // считали бы строку, которой оператор уже не управляет.
  useEffect(() => {
    setBulkDraft((previous) => {
      const stale: number[] = [];
      for (const key of Object.keys(previous)) {
        const taskId = Number(key);
        if (!bulkSelection.selectedIds.has(taskId)) stale.push(taskId);
      }
      return stale.length > 0 ? withoutDraftIds(previous, stale) : previous;
    });
  }, [bulkSelection.selectedIds]);
  const locationRef = useRef(location);
  locationRef.current = location;

  useEffect(() => {
    setBulkMode(searchParams.get("bulk") === "1");
  }, [searchParams]);

  /**
   * Действие, которое теряет черновик, спрашивает подтверждение (#283): выход
   * из режима, Escape и смена участка при непустом черновике — через окно.
   * Пустой черновик не спрашивает ничего.
   */
  const requestDraftGuardedAction = useCallback(
    (action: () => void) => {
      if (isDraftEmpty(bulkDraft)) {
        action();
        return;
      }
      setDraftExitAction(() => action);
    },
    [bulkDraft],
  );

  const toggleBulkMode = useCallback(
    (force?: boolean) => {
      const nextBulk = force !== undefined ? force : !bulkMode;
      if (nextBulk) {
        setBulkMode(true);
        return;
      }
      requestDraftGuardedAction(() => {
        setBulkMode(false);
        setBulkDraft({});
        setBulkShortageStrategy(null);
        bulkSelection.clear();
      });
    },
    [bulkMode, bulkSelection, requestDraftGuardedAction],
  );
  const handleDailyPlanModeChange = useCallback((creating: boolean) => {
    setCreatingDailyPlan(creating);
  }, []);

  const { data: sections } = useQuery({
    queryKey: queryKeys.sections.all(),
    queryFn: listSections,
  });

  const selectedSection = useMemo(
    () => (sections || []).find((s) => s.id === sectionId) || null,
    [sections, sectionId]
  );

  const { data: summary } = useQuery({
    queryKey: queryKeys.shopfloor.summary(),
    queryFn: getSectionsSummary,
    enabled: me != null,
    retry: false,
    // Загрузка участков на плитках доски: коллега завершил задачу — счётчик
    // должен обновиться без F5 (#206, ADR-0041).
    ...operationalPollingOptions,
  });

  const lockedSection = useMemo(() => {
    if (!isSingleWindow || !sections || lockedSectionId === null) return null;
    return sections.find((s) => s.id === lockedSectionId && s.is_active) || null;
  }, [isSingleWindow, sections, lockedSectionId]);
  const isSingleWindowBlocked = isSingleWindow && !lockedSection;

  const selectedSectionIsStock = useMemo(
    () => (selectedSection ? !isProductionSection(selectedSection.type) : false),
    [selectedSection]
  );

  const requestOptions = useMemo(
    () => (isSingleWindow && lockedSectionId !== null ? { singleSectionLockId: lockedSectionId } : undefined),
    [isSingleWindow, lockedSectionId]
  );

  useEffect(() => {
    if (!sections || sections.length === 0) return;
    if (isSingleWindow) {
      if (lockedSectionId === null) {
        setSectionId(null);
        return;
      }
      const activeLockedSection = sections.find((s) => s.id === lockedSectionId && s.is_active);
      if (!activeLockedSection) {
        setSectionId(null);
        return;
      }
      if (sectionId !== activeLockedSection.id) setSectionId(activeLockedSection.id);
      const expectedPath = `/section-tasks/${activeLockedSection.id}`;
      // Accept URLs with singleWindow=1 and optionally bulk=1
      const sp = new URLSearchParams(location.search);
      const hasSingleWindow = sp.get("singleWindow") === "1";
      const hasBulk = sp.get("bulk") === "1";
      const urlOk = location.pathname === expectedPath && hasSingleWindow && (hasBulk ? sp.toString() === "bulk=1&singleWindow=1" || sp.toString() === "singleWindow=1&bulk=1" : sp.toString() === "singleWindow=1");
      if (!urlOk) {
        const nextSp = new URLSearchParams();
        nextSp.set("singleWindow", "1");
        if (hasBulk) nextSp.set("bulk", "1");
        navigate(`${expectedPath}?${nextSp.toString()}`, { replace: true });
      }
      return;
    }
    const paramId = params.sectionId ? Number(params.sectionId) : null;
    const urlSectionIdChanged = paramId !== urlSectionIdRef.current;
    urlSectionIdRef.current = paramId;
    const validParam = Number.isFinite(paramId) ? sections.find((s) => s.id === paramId) : null;
    if (validParam) {
      if (urlSectionIdChanged && sectionId !== validParam.id) setSectionId(validParam.id);
      return;
    }
    const first =
      sections.find((s) => s.is_active && isProductionSection(s.type)) ||
      sections.find((s) => isProductionSection(s.type)) ||
      sections[0];
    if (!first) return;
    setSectionId(first.id);
    navigate(`/section-tasks/${first.id}`, { replace: true });
  }, [sections, params.sectionId, navigate, sectionId, isSingleWindow, lockedSectionId, location.pathname, location.search]);

  const boardParams = useMemo(
    () => ({
      date_from: dateFrom ? `${dateFrom}T00:00:00` : undefined,
      date_to: dateTo ? `${dateTo}T23:59:59` : undefined,
    }),
    [dateFrom, dateTo]
  );

  // Поиск, фильтр артикула и сортировка принадлежат участку: набор, который
  // доска опубликовала для прежнего участка, под новым не применяется — иначе
  // первый запрос нового участка уходит с чужим фильтром и доска на кадр
  // показывает пустоту (ADR-0060 п.1-2). Тег дешевле сброса в эффекте: он
  // закрывает и плитку, и переход по URL, и опоздавшую публикацию старой доски.
  const [serverQueryFor, setServerQueryFor] = useState<{
    sectionId: number | null;
    query: BoardServerQuery;
  }>({ sectionId: null, query: EMPTY_SERVER_QUERY });
  const serverQuery = serverQueryFor.sectionId === sectionId ? serverQueryFor.query : EMPTY_SERVER_QUERY;
  // Обработчик публикации обязан быть стабильным: он стоит в deps эффекта
  // доски, которая выталкивает наружу свой поиск/фильтры, — инлайновая стрелка
  // замыкала бы рендер в цикл.
  const handleBoardServerQueryChange = useCallback(
    (query: BoardServerQuery) => setServerQueryFor({ sectionId, query }),
    [sectionId],
  );
  // Список отрисованных строк доски: футер считает по нему «вне текущего
  // фильтра: N» (#283). Обработчик стабильный и **идемпотентный**: доска зовёт
  // его из эффекта, а `tasks` у неё не всегда стабилен (`board?.tasks || []`
  // до ответа запроса, `mergeDailyPlanTasks` при выбранном плане) — новый
  // `Set` на каждый вызов зациклил бы рендер.
  const handleVisibleTaskIdsChange = useCallback(
    (ids: number[]) =>
      setVisibleTaskIds((previous) => {
        if (previous.size === ids.length && ids.every((id) => previous.has(id))) return previous;
        return new Set(ids);
      }),
    [],
  );

  const {
    page: boardPage,
    setPage: setBoardPage,
    limit: boardLimit,
    setLimit: setBoardLimit,
    offset: boardOffset,
    getTotalPages: getBoardTotalPages,
    getRangeLabel: getBoardRangeLabel,
  } = usePaginatedTableQuery({
    resetPageDeps: [
      sectionId,
      boardParams,
      serverQuery,
      requestOptions?.singleSectionLockId ?? null,
    ],
  });

  const boardQueryParams = useMemo(
    () => ({
      ...boardParams,
      ...serverQuery,
      limit: boardLimit,
      offset: boardOffset,
    }),
    [boardParams, serverQuery, boardLimit, boardOffset],
  );

  // Дерево держится на смене страницы, фильтра и сортировки, но НЕ через смену
  // участка: участок переключается плитками без размонтирования, и placeholder
  // оставил бы под шапкой нового участка задания прежнего — вместе с
  // действиями над ними (ADR-0044).
  const { data: board, isPending: boardPending } = useQuery({
    queryKey: queryKeys.shopfloor.board(sectionId as number, {
      ...boardQueryParams,
      singleSectionLockId: requestOptions?.singleSectionLockId ?? null,
    }),
    queryFn: () => getSectionBoard(sectionId as number, boardQueryParams, requestOptions),
    enabled: sectionId !== null && me != null && !isSingleWindowBlocked,
    retry: false,
    // Доска участка — операционный экран: задания в работе меняют соседи по
    // смене, и перечитывание по таймеру видно без F5 (#206, ADR-0041).
    ...operationalPollingOptions,
    placeholderData: keepPreviousDataForScope<SectionBoardResponse>(
      (key) => key[1],
      sectionId,
    ),
  });

  // Справочник значений серверных колонок (#211): поповер не зависит от
  // страницы, поэтому значения спрашиваются отдельно — по тем же фильтрам, что
  // и доска. Ключ живёт под префиксом доски, и её инвалидация обновляет
  // справочник вместе с ней.
  const boardColumnValuesQueries = useQueries({
    queries: BOARD_SERVER_VALUE_FIELDS.map((field) => {
      const column = boardColumns.find((candidate) => candidate.filterField === field);
      const valuesParams = buildBoardColumnValuesParams({
        column: column?.apiParam ?? field,
        filters: boardQueryParams,
      });
      return {
        queryKey: queryKeys.shopfloor.boardColumnValues(sectionId as number, {
          ...valuesParams,
          singleSectionLockId: requestOptions?.singleSectionLockId ?? null,
        }),
        queryFn: () =>
          getSectionBoardColumnValues(sectionId as number, valuesParams, requestOptions),
        enabled: sectionId !== null && me != null,
        retry: false,
      };
    }),
  });
  const boardFilterValueOptions = useMemo(() => {
    const options: Partial<Record<TaskSortField, string[]>> = {};
    BOARD_SERVER_VALUE_FIELDS.forEach((field, index) => {
      const values = boardColumnValuesQueries[index]?.data?.values;
      if (values) options[field] = values;
    });
    return options;
  }, [boardColumnValuesQueries]);
  const { data: dailyPlans, isLoading: dailyPlansLoading } = useQuery({
    queryKey: queryKeys.dailyPlans.list(sectionId as number),
    queryFn: () => listDailyPlans(sectionId as number, requestOptions),
    enabled: sectionId !== null && me != null && !isSingleWindowBlocked,
    retry: false,
  });

  const selectedPlanIdList = useMemo(
    () => [...selectedPlanIds].sort((left, right) => left - right),
    [selectedPlanIds],
  );
  const selectedPlanQueries = useQueries({
    queries: selectedPlanIdList.map((planId) => ({
      queryKey: queryKeys.dailyPlans.composition(planId),
      queryFn: () => getDailyPlanComposition(planId, requestOptions),
      enabled: me != null && !isSingleWindowBlocked,
      retry: false,
    })),
  });
  const selectedCompositionsLoading = selectedPlanQueries.some((query) => query.isLoading);
  const selectedCompositionItems = useMemo(
    () => selectedPlanQueries.flatMap((query) => query.data?.items ?? []),
    [selectedPlanQueries],
  );
  const createPlanMutation = useMutation({
    mutationFn: (payload: CreateDailyPlanInput) => createDailyPlan(payload, requestOptions),
    onSuccess: async (plan) => {
      // Состав и список дневных планов лежат под корнем `shopfloor-daily-plans`,
      // который целиком входит в домен `shopfloor` — точечный ключ не нужен.
      await invalidateAfter(queryClient, "dailyPlanChanged");
      setSelectedPlanIds(new Set([plan.id]));
      bulkSelection.clear();
      revokeSelection.clear();
      setBulkMode(false);
    },
    onError: (error) => {
      toast({ title: "Не удалось создать план", description: getErrorMessage(error), variant: "destructive" });
    },
  });
  // Ошибка создания плана относится к прежнему участку: под новым она держала бы
  // форму создания открытой, потому что панель гасит режим только когда ошибки
  // нет (ADR-0060 п.1). `reset` берём из ref: эффект не должен зависеть от
  // объекта мутации, который пересоздаётся на каждом рендере.
  const resetCreatePlanRef = useRef(createPlanMutation.reset);
  resetCreatePlanRef.current = createPlanMutation.reset;
  useEffect(() => {
    resetCreatePlanRef.current();
  }, [sectionId]);
  const revokePlanItemsMutation = useMutation({
    mutationFn: async (items: DailyPlanCompositionItem[]) => {
      const results = await Promise.allSettled(
        items.map((item) => revokeDailyPlanItem(item.daily_plan_id, item.work_task_id, requestOptions)),
      );
      const failed = results.filter((result) => result.status === "rejected").length;
      if (failed > 0) {
        throw new Error(`Не удалось отозвать задания: ${failed} из ${items.length}`);
      }
    },
    onSuccess: async () => {
      await invalidateAfter(queryClient, "dailyPlanChanged");
      revokeSelection.clear();
    },
    onError: (error) => {
      toast({ title: "Не удалось отозвать задания", description: getErrorMessage(error), variant: "destructive" });
    },
  });

  const boardTotal = board?.total ?? 0;
  const boardTotalPages = getBoardTotalPages(boardTotal);

  const { data: stats } = useQuery({
    queryKey: ["shopfloor-stats", sectionId, dateFrom, dateTo, requestOptions?.singleSectionLockId ?? null],
    queryFn: () =>
      getSectionDailyStats(sectionId as number, {
        date_from: `${dateFrom}T00:00:00`,
        date_to: `${dateTo}T23:59:59`,
      }, requestOptions),
    enabled: sectionId !== null && me != null && !!dateFrom && !!dateTo && !isSingleWindow && !isSingleWindowBlocked,
    retry: false,
  });

  const pushActionLog = useCallback((_payload: any) => {}, []);

  const openActionDialog = useCallback((_type: TaskActionDialogType, task: SectionBoardTask) => {
    const now = nowLocalDateTimeParts();
    setActionDialog({ open: true, type: "complete", task });
    setPerformedDate(now.date);
    setPerformedShift("1");
    setActionComment("");
    setConflictHint(null);
    setActionQty("");
    setDefectQty("");
  }, []);

  // Escape key: double-Escape exits single-window mode, single-Escape exits bulk mode.
  useEffect(() => {
    if (!bulkMode && !isSingleWindow) return;
    const DOUBLE_ESCAPE_TIMEOUT_MS = 1500;
    const lastEscapeAtRef = { current: 0 };
    let resetTimer: ReturnType<typeof setTimeout> | null = null;
    const handler = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (actionDialog.open || bulkResultsOpen) return;
      // Окно плана и предпросмотра печати тоже Radix: перечислить их флагами
      // значит забыть один. Пока открыто любое окно, страница клавиши не трогает.
      if (isAnyDialogOpen()) return;
      e.preventDefault();
      if (isSingleWindow) {
        const now = Date.now();
        if (now - lastEscapeAtRef.current < DOUBLE_ESCAPE_TIMEOUT_MS) {
          if (resetTimer) {
            clearTimeout(resetTimer);
            resetTimer = null;
          }
          lastEscapeAtRef.current = 0;
          navigate(sectionId ? `/section-tasks/${sectionId}` : "/section-tasks");
        } else {
          lastEscapeAtRef.current = now;
          toast({
            variant: "default",
            title: "Нажмите Escape ещё раз, чтобы выйти из режима одного окна",
          });
          if (resetTimer) clearTimeout(resetTimer);
          resetTimer = setTimeout(() => {
            lastEscapeAtRef.current = 0;
            resetTimer = null;
          }, DOUBLE_ESCAPE_TIMEOUT_MS);
        }
      } else if (bulkMode) {
        // Escape снимает выделение, а с непустым черновиком — спрашивает, потому
        // что снятое выделение уносит и набранное количество (#283).
        if (!isDraftEmpty(bulkDraft)) {
          setDraftExitAction(() => () => {
            setBulkMode(false);
            setBulkDraft({});
            setBulkShortageStrategy(null);
            bulkSelection.clear();
          });
        } else if (bulkSelection.selectedCount > 0) {
          bulkSelection.clear();
        } else {
          toggleBulkMode();
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => {
      window.removeEventListener("keydown", handler);
      if (resetTimer) clearTimeout(resetTimer);
    };
  }, [
    bulkMode,
    bulkDraft,
    bulkSelection,
    isSingleWindow,
    actionDialog.open,
    bulkResultsOpen,
    navigate,
    sectionId,
    toggleBulkMode,
  ]);

  const closeActionDrawer = useCallback(() => {
    setActionDialog({ open: false, type: "complete", task: null });
    setShortageStrategy("fail");
  }, []);

  /**
   * Запись массового ввода (#283): одна entry на задачу через
   * `bulkCompleteTasks`, `auto_transfer_next: true` — как у одиночного
   * завершения (#187): передачу создаёт записанный факт, а не отдельная кнопка.
   * Черновик чистится только после успешной записи: при частичном отказе
   * оператор видит окно результатов и может повторить, ничего не потеряв.
   */
  const bulkDraftMutation = useMutation({
    mutationFn: (entries: BulkCompleteEntry[]) => bulkCompleteTasks(entries, requestOptions),
    onSuccess: async (response, entries) => {
      const results: BulkActionResultItem<number>[] = response.results.map((result) => ({
        id: result.id,
        status: result.status,
        reason: result.reason,
      }));
      const summary = summarizeBulkResults(results);
      const totals = entries.reduce(
        (acc, entry) => ({
          good: acc.good + toQtyInteger(entry.good_quantity),
          defect: acc.defect + toQtyInteger(entry.defect_quantity ?? "0"),
        }),
        { good: 0, defect: 0 },
      );

      if (summary.failed > 0) {
        setBulkResults(results);
        setBulkSummary(summary);
        setBulkResultsOpen(true);
        toast({
          title: summary.success > 0 ? "Частичный успех" : "Не удалось записать факт",
          description: `${summary.success} успешно, ${summary.failed} ошибок`,
          variant: "destructive",
        });
      } else {
        toast({
          title: "Факт записан",
          description: `Заданий: ${summary.success} · годные ${fmtQty(totals.good)}, брак ${fmtQty(totals.defect)}`,
          variant: "success",
        });
        clearBulkDraft();
        setBulkMode(false);
      }
      await invalidateAfter(queryClient, "sectionTaskChanged");
    },
    onError: (error) => {
      toast({
        title: "Не удалось записать факт",
        description: getErrorMessage(error),
        variant: "destructive",
      });
    },
  });

  const completeMutation = useMutation({
    mutationFn: ({ taskId, payload }: { taskId: number; payload: Parameters<typeof completeTask>[1]; task?: SectionBoardTask }) =>
      completeTask(taskId, payload, requestOptions),
    onSuccess: (data, variables) => {
      const task = variables.task;
      const goodQty = variables.payload.good_quantity;
      const defectQty = variables.payload.defect_quantity;
      const comment = variables.payload.comment;
      const sectionInfo = selectedSection ? `на участке "${selectedSection.name}" (${selectedSection.code})` : "";

      const taskDetails = task
        ? `для операции "${task.operation_name || task.operation_code || "Операция"}" (арт. ${task.display_sku || task.product_sku})`
        : `for task #${variables.taskId}`;

      const message = `Успешно подтверждено выполнение ${taskDetails} ${sectionInfo}. Введено: годные = ${goodQty} шт., брак = ${defectQty} шт.${comment ? ` (комментарий: "${comment}")` : ""}.`;

      toast({ title: "Факт сохранен", variant: "success" });
      pushActionLog({
        status: "success",
        title: "Факт подтвержден",
        message,
        taskIds: [variables.taskId],
        productSku: task?.display_sku || task?.product_sku,
        operationName: task?.operation_name || task?.operation_code || undefined,
        qtyText: `годн: ${goodQty}, брак: ${defectQty}`,
        comment: comment || undefined,
      });
      void invalidateAfter(queryClient, "sectionTaskChanged");
      closeActionDrawer();
      setConflictHint(null);
    },
    onError: (err, variables) => {
      const message = getErrorMessage(err);
      const task = variables.task;
      const sectionInfo = selectedSection ? `на участке "${selectedSection.name}" (${selectedSection.code})` : "";
      
      const taskDetails = task
        ? `для операции "${task.operation_name || task.operation_code || "Операция"}" (арт. ${task.display_sku || task.product_sku})`
        : `for task #${variables.taskId}`;

      toast({ title: "Ошибка", description: message, variant: "destructive" });
      pushActionLog({
        status: "error",
        title: "Ошибка подтверждения факта",
        message: `Не удалось подтвердить выполнение ${taskDetails} ${sectionInfo}. Причина: ${message}`,
        taskIds: [variables.taskId],
        productSku: task?.display_sku || task?.product_sku,
        operationName: task?.operation_name || task?.operation_code || undefined,
        errorDetails: message,
      });
      setConflictHint(conflictHintFromError(message));
    },
  });

  const pendingMutation = completeMutation.isPending;

  /**
   * Одиночное завершение из строки доски (#283): групповой путь ушёл в инлайн
   * и футер, поэтому диалог отвечает только за одну задачу.
   */
  const submitAction = useCallback(() => {
    const task = actionDialog.task;
    if (!task) return;

    const effectivePerformedAt = `${performedDate}T${performedShift === "1" ? "08:00" : "20:00"}`;
    const effectiveAccountedAt = nowLocalDateTime();
    const executorUserId = me?.id;

    // Трансформация габаритов (ADR-0002, раскрой): факт считается в заготовках
    // ВХОДА, лимит — остаток входа, и стратегия дефицита к ней не применяется
    // вовсе: иначе «в работе» = issued − completed сравнивало бы разные
    // размерности, а бэкенд проверяет остаток входа.
    const isTransformTask = !!task.transforms_dimensions && (task.outputs?.length ?? 0) > 0;

    // Ввод в двух режимах: «+100» — добавить, «500» — факт станет 500. На сервер
    // уходит порция, а не набранное число: бэкенд кладёт проводку ровно на
    // введённое количество, и отрицательных он не знает.
    const recordedGood = isTransformTask
      ? toQtyInteger(task.input_consumed_quantity ?? "0")
      : toQtyInteger(task.cache.completed_quantity);
    const goodResolution = resolveFactQuantity(actionQty, recordedGood);
    const defectResolution = resolveFactQuantity(
      defectQty,
      toQtyInteger(task.cache.rejected_quantity),
    );
    const invalidReason =
      goodResolution.kind === "invalid"
        ? goodResolution.reason
        : defectResolution.kind === "invalid"
          ? defectResolution.reason
          : null;
    if (invalidReason) {
      const text = actionReasonText(invalidReason);
      toast({ title: "Ошибка", description: text, variant: "destructive" });
      setConflictHint(text);
      return;
    }
    const good = goodResolution.kind === "write" ? goodResolution.quantity : 0;
    const defect = defectResolution.kind === "write" ? defectResolution.quantity : 0;
    if (good + defect <= 0) {
      toast({ title: "Ошибка", description: "Укажите факт или брак", variant: "destructive" });
      setConflictHint("Укажите хотя бы одно количество: годные или брак.");
      return;
    }
    const inWork = isTransformTask
      ? Math.max(
          0,
          toQtyInteger(task.input_quantity ?? "0") -
            toQtyInteger(task.input_consumed_quantity ?? "0") -
            toQtyInteger(task.cache.rejected_quantity),
        )
      : Math.max(
          0,
          toQtyInteger(task.cache.issued_quantity) -
            toQtyInteger(task.cache.completed_quantity) -
            toQtyInteger(task.cache.rejected_quantity),
        );
    const available = isTransformTask ? 0 : Math.max(0, toQtyInteger(task.cache.available_quantity));
    const isShortage = !isTransformTask && inWork > 0 && good + defect > Math.max(inWork, inWork + available);

    if (isShortage && shortageStrategy === "fail") {
      setConflictHint(
        `Сумма факта и брака превышает доступный объем (${fmtQty(String(inWork + available))}).`,
      );
      return;
    }

    const blockReason = getCompletionBlockReason(task);
    if (blockReason) {
      toast({
        title: "Нельзя завершить задание",
        description: actionReasonText(blockReason),
        variant: "destructive",
      });
      return;
    }
    completeMutation.mutate({
      taskId: task.id,
      task,
      payload: {
        good_quantity: String(good),
        defect_quantity: String(defect),
        comment: actionComment || undefined,
        idempotency_key: makeIdempotencyKey("complete"),
        executor_user_id: executorUserId,
        performed_at: effectivePerformedAt,
        accounted_at: effectiveAccountedAt,
        shortage_strategy: shortageStrategy,
        auto_transfer_next: true,
      },
    });
  }, [
    actionDialog,
    actionQty,
    performedDate,
    performedShift,
    me?.id,
    completeMutation,
    actionComment,
    defectQty,
    shortageStrategy,
  ]);

  // Идентичность массива — часть контракта с доской: её эффект публикует
  // видимые строки, и литерал `[]` на каждый рендер был бы источником цикла.
  const tasks = useMemo(() => board?.tasks ?? [], [board]);
  const displayedTasks = selectedPlanIds.size === 0
    ? tasks
    : mergeDailyPlanTasks(selectedPlanQueries.flatMap((query) => (
        query.data ? [query.data.items] : []
      )));
  // Вкладка «План» без выбранного плана — это «все актуальные задания
  // участка»: завершённые строки живут только в составе конкретного плана
  // (docs/daily-plans-spec.md, «Режим `План`»).
  const planBoardTasks = useMemo(
    () => (selectedPlanIds.size === 0
      ? getDailyPlanCreationCandidates(tasks)
      : displayedTasks),
    [tasks, displayedTasks, selectedPlanIds],
  );
  const selectedTasks = useMemo(
    () => tasks.filter((t) => bulkSelection.selectedIds.has(t.id)),
    [tasks, bulkSelection.selectedIds],
  );

  /**
   * Итог черновика и причина недоступности подтверждения (#283). Причины — из
   * общего словаря (#193): «нет заданий для завершения» (введено, но завершать
   * нечего), «введите количество» (черновик пуст) и «выберите, что делать с
   * излишком» (дефицит без выбранной стратегии). Панель массовых операций
   * молчала о третьей и не отправляла стратегию вовсе.
   */
  const bulkDraftShortage = useMemo(
    () => draftShortage(selectedTasks, bulkDraft),
    [selectedTasks, bulkDraft],
  );
  const bulkConfirmBlockReason: ActionReasonCode | null = useMemo(() => {
    const { entries, skipped } = draftEntries(selectedTasks, bulkDraft);
    if (entries.length === 0) {
      return skipped.length > 0 ? "bulk_nothing_to_complete" : "bulk_no_quantity";
    }
    if (bulkDraftShortage && !bulkShortageStrategy) return "no_shortage_strategy";
    return null;
  }, [selectedTasks, bulkDraft, bulkDraftShortage, bulkShortageStrategy]);

  const clearBulkDraft = useCallback(() => {
    setBulkDraft({});
    setBulkShortageStrategy(null);
    setBulkComment("");
    bulkSelection.clear();
  }, [bulkSelection]);

  /** Запись черновика: одна entry на задачу, стратегия дефицита — из футера. */
  const confirmBulkDraft = useCallback(() => {
    if (bulkConfirmBlockReason !== null) return;
    const { entries } = draftEntries(selectedTasks, bulkDraft);
    const effectivePerformedAt = `${bulkPerformedDate}T${bulkPerformedShift === "1" ? "08:00" : "20:00"}`;
    const effectiveAccountedAt = nowLocalDateTime();
    bulkDraftMutation.mutate(
      entries.map((entry) => ({
        task_id: entry.taskId,
        good_quantity: String(entry.good.quantity),
        defect_quantity: String(entry.defect.quantity),
        comment: bulkComment.trim() || undefined,
        idempotency_key: makeIdempotencyKey(`bulk-complete-${entry.taskId}`),
        executor_user_id: me?.id,
        performed_at: effectivePerformedAt,
        accounted_at: effectiveAccountedAt,
        shortage_strategy: bulkShortageStrategy ?? undefined,
        // Авто-передача при записи факта обязательна (#187): передачу создаёт
        // факт, а не отдельная кнопка.
        auto_transfer_next: true,
      })),
    );
  }, [
    bulkConfirmBlockReason,
    selectedTasks,
    bulkDraft,
    bulkPerformedDate,
    bulkPerformedShift,
    bulkComment,
    bulkShortageStrategy,
    bulkDraftMutation,
    me?.id,
  ]);
  const handleToggleRevokeItem = useCallback(
    (workTaskId: number) => {
      if (selectedCompositionItems.some((item) => item.work_task_id === workTaskId)) {
        revokeSelection.selectOne(workTaskId);
      }
    },
    [revokeSelection, selectedCompositionItems],
  );
  const handleConfirmRevoke = useCallback(() => {
    const items = selectedCompositionItems.filter((item) => revokeSelection.isSelected(item.work_task_id));
    if (items.length > 0) revokePlanItemsMutation.mutate(items);
  }, [revokeSelection, revokePlanItemsMutation, selectedCompositionItems]);
  const handleCreatePlan = useCallback(
    (planDate: string) => {
      if (sectionId === null || selectedTasks.length === 0) return;
      createPlanMutation.mutate({
        section_id: sectionId,
        plan_date: planDate,
        work_task_ids: selectedTasks.map((task) => task.id),
      });
    },
    [createPlanMutation, sectionId, selectedTasks],
  );

  const togglePlanSelection = useCallback((planId: number) => {
    revokeSelection.clear();
    setSelectedPlanIds((current) => {
      const next = new Set(current);
      if (next.has(planId)) next.delete(planId);
      else next.add(planId);
      return next;
    });
  }, [revokeSelection]);
  const selectOnlyPlan = useCallback((planId: number) => {
    revokeSelection.clear();
    setSelectedPlanIds(new Set([planId]));
  }, [revokeSelection]);
  const clearPlanSelection = useCallback(() => {
    revokeSelection.clear();
    setSelectedPlanIds(new Set());
  }, [revokeSelection]);

  const handleSelectAll = useCallback((ids: number[]) => {
    bulkSelection.selectAll(ids);
  }, [bulkSelection]);





  const canToggleSingleWindow = sectionId !== null && !isSingleWindowBlocked;
  const selectedSectionColor = selectedSection?.icon_color || "#1D4ED8";
  const selectedSectionTint = selectedSectionColor.startsWith("#") ? `${selectedSectionColor}1A` : "#DBEAFE";

  // Печать — одна кнопка на обе вкладки, в ряду фильтров сразу после поиска
  // (слот `toolbar` доски). Что печатается, решает страница: в модальное окно
  // уходит тот же набор, что видит оператор.
  const printButton = <PlanPrintButton onClick={() => setPlanModalOpen(true)} />;

  return (
    <>
      {!isSingleWindow && (
        <header className="page-header">
          <div>
            <h1 className="page-title">Участки</h1>
            <p className="page-subtitle">
              Операционный пульт: быстрый выбор участка, выдача, факт, передача и приемка.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="rounded-md border border-slate-700 px-3 py-2 text-xs font-semibold uppercase tracking-wide hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
              disabled={!canToggleSingleWindow}
              onClick={() => {
                if (!sectionId) return;
                navigate(`/section-tasks/${sectionId}?singleWindow=1`);
              }}
            >
              Включить режим одного окна
            </button>
          </div>
        </header>
      )}

      <section className="space-y-4">
        {!isSingleWindow && (
          <div className="space-y-2">
            <div className="text-sm font-semibold text-slate-700">Выберите рабочий участок</div>
            <SectionSwitcherTiles
              sections={(sections || []).filter((section) => section.is_active && isProductionSection(section.type))}
              summary={summary?.sections || []}
              selectedSectionId={sectionId}
              onSelect={(nextId) => {
                requestDraftGuardedAction(() => {
                  setSectionId(nextId);
                  navigate(`/section-tasks/${nextId}`);
                });
              }}
            />
          </div>
        )}
        {selectedSection && !selectedSectionIsStock && (
          <div
            className="rounded-xl border px-4 py-3"
            style={{ borderColor: selectedSectionColor, backgroundColor: selectedSectionTint }}
          >
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-3 min-w-0 flex-wrap">
                <>
                  <span
                    className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg"
                    style={{ backgroundColor: "#FFFFFFB3", color: selectedSectionColor }}
                  >
                    {selectedSection.icon ? renderIcon(selectedSection.icon, "h-5 w-5") : <span className="h-2.5 w-2.5 rounded-full bg-current" />}
                  </span>
                  <div className="min-w-0 truncate text-xl font-bold leading-tight text-slate-900">
                    {selectedSection.name}
                  </div>
                </>
                {!isSingleWindowBlocked && sectionId && (
                  <SectionPanelToggles
                    mode={sectionContentMode}
                    onChange={setSectionContentMode}
                  />
                )}
              </div>
              <div className="shrink-0 flex flex-col items-end gap-2">
                <div className="rounded-md border border-white/70 bg-white/70 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-700">
                  {isSingleWindow ? "Режим одного окна" : "Рабочий участок"}
                </div>
                {isSingleWindow && (
                  <button
                    type="button"
                    className="rounded-md border border-slate-700 bg-white/80 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-800 hover:bg-white"
                    onClick={() => navigate(sectionId ? `/section-tasks/${sectionId}` : "/section-tasks")}
                  >
                    Выйти из режима одного окна
                  </button>
                )}
              </div>
            </div>
          </div>
        )}

        {isSingleWindowBlocked && (
          <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
            <div className="font-semibold">Режим одного окна недоступен</div>
            <div className="mt-1">
              {!isRequestedSectionIdValid
                ? "Не задан корректный участок в URL. Откройте /section-tasks/<id>?singleWindow=1."
                : "Участок не найден или недоступен. Доступ к другим участкам в этом режиме заблокирован."}
            </div>
            <button
              type="button"
              className="mt-3 rounded-md border border-amber-700 px-3 py-1.5 text-xs font-medium hover:bg-amber-100"
              onClick={() => navigate("/section-tasks")}
            >
              Выйти из режима одного окна
            </button>
          </div>
        )}

        {!isSingleWindowBlocked && selectedSectionIsStock && (
          <div className="rounded-lg border border-slate-300 bg-slate-50 p-4 text-sm text-slate-800">
            <div className="font-semibold">Это складской участок</div>
            <div className="mt-1">
              Доска задач производственного цеха для раздела «{selectedSection?.name ?? ""}» не предусмотрена.
              Управление остатками и передачами — в разделах «Передачи» и «ГХП».
            </div>
            <button
              type="button"
              className="mt-3 rounded-md border border-slate-700 px-3 py-1.5 text-xs font-medium hover:bg-slate-100"
              onClick={() => navigate("/section-tasks")}
            >
              К списку производственных участков
            </button>
          </div>
        )}


        {!isSingleWindowBlocked && sectionId && (
          <div className="space-y-4">
            {isTasksPanelVisible(sectionContentMode) && (
              <>
                <div className={cn("grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_280px]", bulkMode && bulkSelection.selectedCount > 0 && !creatingDailyPlan && "pb-44")}>
                  {/* `key` — чтобы поиск, фильтры и сортировка прежнего участка
                      умирали вместе с ним, а не жили под шапкой нового (ADR-0060 п.1). */}
                  <SectionTasksBoard
                    key={sectionId}
                    toolbar={
                      <div className="flex items-center gap-2">
                        <DateRangePicker
                          compact
                          from={dateRange.from}
                          to={dateRange.to}
                          onChange={setDateRange}
                          placeholder="Период"
                        />
                        {printButton}
                      </div>
                    }
                    tasks={displayedTasks}
                    total={displayedTasks.length}
                    isLoading={boardPending || selectedCompositionsLoading}
                    filterValueOptions={boardFilterValueOptions}
                    mode={viewMode}
                    onModeChange={setViewMode}
                    onAction={openActionDialog}
                    hasPackaging={selectedSection?.has_packaging}
                    showStatusFilters
                    bulkMode={bulkMode || creatingDailyPlan}
                    onBulkModeChange={toggleBulkMode}
                    bulkSelection={bulkMode || creatingDailyPlan ? bulkSelection : undefined}
                    bulkDraft={bulkMode && !creatingDailyPlan ? bulkDraft : undefined}
                    onBulkDraftChange={bulkMode && !creatingDailyPlan ? setBulkDraft : undefined}
                    onVisibleTaskIdsChange={handleVisibleTaskIdsChange}
                    profile={profile}
                    onSelectAllVisible={handleSelectAll}
                    page={selectedPlanIds.size > 0 ? 1 : boardPage}
                    setPage={selectedPlanIds.size > 0 ? () => {} : setBoardPage}
                    limit={boardLimit}
                    setLimit={setBoardLimit}
                    totalPages={selectedPlanIds.size > 0 ? 1 : boardTotalPages}
                    rangeLabel={selectedPlanIds.size > 0 ? `${displayedTasks.length} заданий` : getBoardRangeLabel(tasks.length, boardTotal, { onPage: true })}
                    onServerQueryChange={handleBoardServerQueryChange}
                  />
                  <DailyPlansPanel
                    plans={dailyPlans ?? []}
                    selectedPlanIds={selectedPlanIds}
                    onSelectPlan={selectOnlyPlan}
                    onTogglePlan={togglePlanSelection}
                    onClearPlans={clearPlanSelection}
                    onOpenPlans={() => setSectionContentMode("plan")}
                    opensPlans
                    isLoading={dailyPlansLoading}
                  />
                </div>

                {!isSingleWindow && stats && (
                  <div className="rounded-lg border p-4">
                    <h3 className="text-sm font-semibold mb-3">Статистика по дням</h3>
                    <div className="overflow-auto">
                      <table className="w-full text-sm">
                        <thead className="border-b bg-muted/50">
                          <tr>
                            <th className="text-left p-2">Дата</th>
                            <th className="text-left p-2">Факт</th>
                            <th className="text-left p-2">Брак</th>
                            <th className="text-left p-2">Операций</th>
                            <th className="text-left p-2">Ср. задержка учета</th>
                          </tr>
                        </thead>
                        <tbody>
                          {stats.daily_stats.map((row: DailyStatsRow) => (
                            <tr key={row.date} className="border-b">
                              <td className="p-2">{row.date}</td>
                              <td className="p-2">{fmtQty(row.good_quantity)}</td>
                              <td className="p-2">{parseFloat(row.rejected_quantity) > 0 ? <span className="text-red-600 font-medium">{fmtQty(row.rejected_quantity)}</span> : fmtQty(row.rejected_quantity)}</td>
                              <td className="p-2">{row.op_count}</td>
                              <td className="p-2">
                                {(() => {
                                  const delaySec = parseFloat(row.avg_accounting_delay_seconds);
                                  if (!Number.isFinite(delaySec) || delaySec === 0) return "—";
                                  const min = Math.floor(delaySec / 60);
                                  const sec = Math.round(delaySec % 60);
                                  return `${min}м ${sec}с`;
                                })()}
                              </td>
                            </tr>
                          ))}
                          {stats.daily_stats.length === 0 && (
                            <tr><td colSpan={5} className="p-4 text-center text-muted-foreground">Нет данных за период</td></tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </>
            )}

            {isPlanPanelVisible(sectionContentMode) && (
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">
                <div className="min-w-0 space-y-3">
                  <div>
                    <h2 className="text-lg font-semibold">План участка</h2>
                    <p className="text-sm text-muted-foreground">
                      {selectedPlanIds.size === 0
                        ? "Все актуальные задания участка"
                        : `Выбрано планов: ${selectedPlanIds.size}`}
                    </p>
                  </div>
                  <SectionTasksBoard
                    key={sectionId}
                    toolbar={printButton}
                    tasks={planBoardTasks}
                    total={planBoardTasks.length}
                    isLoading={boardPending || selectedCompositionsLoading}
                    mode={sectionContentMode === "plan" ? { active: true, waiting: true, completed: true } : viewMode}
                    onModeChange={setViewMode}
                    showStatusFilters={selectedPlanIds.size > 0}
                    showCompletedStatus={selectedPlanIds.size > 0}
                    onAction={openActionDialog}
                    readOnly={!creatingDailyPlan}
                    hasPackaging={selectedSection?.has_packaging}
                    profile={profile}
                    bulkMode={creatingDailyPlan ? bulkMode || creatingDailyPlan : false}
                    onBulkModeChange={toggleBulkMode}
                    bulkSelection={creatingDailyPlan ? bulkSelection : undefined}
                    onSelectAllVisible={creatingDailyPlan ? handleSelectAll : undefined}
                    revokeSelection={!creatingDailyPlan && selectedPlanIds.size > 0 ? revokeSelection : undefined}
                    onRevokeItem={!creatingDailyPlan && selectedPlanIds.size > 0 ? handleToggleRevokeItem : undefined}
                    onConfirmRevoke={!creatingDailyPlan && selectedPlanIds.size > 0 ? handleConfirmRevoke : undefined}
                    isRevoking={revokePlanItemsMutation.isPending}
                    page={1}
                    setPage={() => {}}
                    limit={boardLimit}
                    setLimit={setBoardLimit}
                    totalPages={1}
                    rangeLabel={`${planBoardTasks.length} заданий`}
                    onServerQueryChange={handleBoardServerQueryChange}
                  />
                </div>
                <DailyPlansPanel
                  plans={dailyPlans ?? []}
                  onCreatePlan={handleCreatePlan}
                  selectedTaskCount={selectedTasks.length}
                  onSelectPlan={selectOnlyPlan}
                  selectedPlanIds={selectedPlanIds}
                  onCreateModeChange={handleDailyPlanModeChange}
                  onTogglePlan={togglePlanSelection}
                  onClearPlans={clearPlanSelection}
                  onOpenPlans={() => setSectionContentMode("tasks")}
                  isLoading={dailyPlansLoading}
                  isCreating={createPlanMutation.isPending}
                  createErrorMessage={createPlanMutation.error ? getErrorMessage(createPlanMutation.error) : null}
                />
              </div>
            )}

            {isBalancesPanelVisible(sectionContentMode) && (
              <SectionStockBalances sectionId={sectionId} sectionName={selectedSection?.name} />
            )}
          </div>
        )}
      </section>

      {/* Панель подтверждения массового ввода (#283): итог «к записи», стратегия
          дефицита и сама запись. Показывается только в массовом режиме доски
          задач и не мешает созданию дневного плана. */}
      {isTasksPanelVisible(sectionContentMode) &&
        bulkMode &&
        !creatingDailyPlan &&
        bulkSelection.selectedCount > 0 && (
          <BulkCompleteFooter
            selectedTasks={selectedTasks}
            visibleTaskIds={visibleTaskIds}
            draft={bulkDraft}
            performedDate={bulkPerformedDate}
            onPerformedDateChange={setBulkPerformedDate}
            performedShift={bulkPerformedShift}
            onPerformedShiftChange={setBulkPerformedShift}
            comment={bulkComment}
            onCommentChange={setBulkComment}
            shortageStrategy={bulkShortageStrategy}
            onShortageStrategyChange={setBulkShortageStrategy}
            shortage={bulkDraftShortage}
            submitBlockReason={bulkConfirmBlockReason}
            pending={bulkDraftMutation.isPending}
            onConfirm={confirmBulkDraft}
            onCancel={() =>
              requestDraftGuardedAction(() => {
                setBulkDraft({});
                setBulkShortageStrategy(null);
                bulkSelection.clear();
                setBulkMode(false);
              })
            }
          />
        )}

      <BulkDraftExitDialog
        open={draftExitAction !== null}
        summary={draftTotals(selectedTasks, bulkDraft)}
        onCancel={() => setDraftExitAction(null)}
        onConfirm={() => {
          const action = draftExitAction;
          setDraftExitAction(null);
          setBulkDraft({});
                setBulkShortageStrategy(null);
          action?.();
        }}
      />

      <TaskActionDrawer
        open={actionDialog.open}
        onOpenChange={(open) => {
          if (!open) closeActionDrawer();
          else setActionDialog((prev) => ({ ...prev, open }));
        }}
        task={actionDialog.task}
        actionQty={actionQty}
        setActionQty={setActionQty}
        defectQty={defectQty}
        setDefectQty={setDefectQty}
        performedDate={performedDate}
        setPerformedDate={setPerformedDate}
        performedShift={performedShift}
        setPerformedShift={setPerformedShift}
        actionComment={actionComment}
        setActionComment={setActionComment}
        shortageStrategy={shortageStrategy}
        setShortageStrategy={setShortageStrategy}
        pending={pendingMutation}
        conflictHint={conflictHint}
        onSubmit={submitAction}
      />

      {/* Bulk results dialog */}
      <BulkResultsDialog
        open={bulkResultsOpen}
        onOpenChange={setBulkResultsOpen}
        title="Результат массовой операции"
        summary={bulkSummary}
        results={bulkResults}
      />

      {/* Plan modal */}
      <PlanModal
        open={planModalOpen}
        onOpenChange={setPlanModalOpen}
        sectionId={sectionId ?? 0}
        sectionName={selectedSection?.name || "—"}
        sectionCode={selectedSection?.code || null}
        hasPackaging={selectedSection?.has_packaging}
        tasks={sectionContentMode === "plan" ? planBoardTasks : displayedTasks}
        availableOperations={board?.available_operations || []}
      />
      {/* Daily plans are created inline in the plans panel. */}



    </>
  );
}
