import { useCallback, useEffect, useMemo, useState, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { apiClient, getErrorMessage } from "@/shared/api/client";
import { listSections } from "@/shared/api/sections";
import {
  bulkCompleteTasks,
  completeTask,
  getSectionBoard,
  getSectionDailyStats,
  getSectionsSummary,
  type DailyStatsRow,
  type SectionBoardTask,
  type TaskGroup,
} from "@/shared/api/shopfloor";
import { queryKeys } from "@/shared/api/queryKeys";
import { DateRangePicker, renderIcon, toast, Button, type DateRangeValue } from "@/shared/ui";
import { useBulkSelection } from "@/shared/bulk";
import { BulkResultsDialog, summarizeBulkResults, type BulkActionResultItem, type BulkActionSummary, type BulkRunnerProgress } from "@/shared/bulk";
import { SectionSwitcherTiles } from "../components/SectionSwitcherTiles";
import { SectionTasksBoard, type TaskActionDialogType, type TaskBoardViewMode } from "../components/SectionTasksBoard";
import { TaskActionDrawer } from "../components/TaskActionDrawer";
import { BulkOperationsPanel } from "../components/BulkOperationsPanel";
import { PlanModal } from "../components/PlanModal";
import { PRESET_PROFILES, type GroupingProfile } from "../lib/groupingProfiles";
import { createAuditLog, getAuditLogs, type AuditLogEntry } from "@/shared/api/auditLogs";

type MeResponse = {
  id: number;
  email: string;
  full_name: string;
  role: "admin" | "planner" | "section_manager" | "operator" | "viewer";
  section_id: number | null;
  is_active: boolean;
};

function fmtQty(value: string): string {
  const n = parseFloat(value);
  if (!Number.isFinite(n)) return "0";
  return String(Math.round(n));
}

function toInteger(value: string | number): number {
  const n = typeof value === "number" ? value : parseFloat(value);
  return Number.isFinite(n) ? Math.round(n) : 0;
}

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
  const profile = PRESET_PROFILES.find((p) => p.id === "sku+routeHistoryAfter") || PRESET_PROFILES[2];

  const [viewMode, setViewMode] = useState<TaskBoardViewMode>({ active: true, waiting: true, completed: false });
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
    tasks: SectionBoardTask[] | null;
  }>({
    open: false,
    type: "complete",
    task: null,
    tasks: null,
  });
  const [actionQty, setActionQty] = useState("");
  const [defectQty, setDefectQty] = useState("");
  const [performedDate, setPerformedDate] = useState("");
  const [performedShift, setPerformedShift] = useState<"1" | "2">("1");
  const [actionComment, setActionComment] = useState("");
  const [planModalOpen, setPlanModalOpen] = useState(false);

  // Bulk mode state
  const [bulkMode, setBulkMode] = useState(searchParams.get("bulk") === "1" || searchParams.get("singleWindow") === "1");
  const bulkSelection = useBulkSelection<number>();
  const activatedSingleWindowRef = useRef(false);

  // Sync bulkMode with URL search params
  useEffect(() => {
    const fromUrl = searchParams.get("bulk") === "1" || searchParams.get("singleWindow") === "1";
    setBulkMode(fromUrl);
  }, [searchParams]);
  const locationRef = useRef(location);
  locationRef.current = location;

  const toggleBulkMode = useCallback((force?: boolean) => {
    setBulkMode((prev) => {
      const nextBulk = force !== undefined ? force : !prev;
      if (!nextBulk) bulkSelection.clear();

      const sp = new URLSearchParams(locationRef.current.search);
      if (nextBulk) {
        sp.set("bulk", "1");
        const swAlready = sp.get("singleWindow") === "1";
        if (!swAlready && sectionId) {
          sp.set("singleWindow", "1");
          activatedSingleWindowRef.current = true;
        }
      } else {
        sp.delete("bulk");
        if (activatedSingleWindowRef.current) {
          sp.delete("singleWindow");
          activatedSingleWindowRef.current = false;
        }
      }
      const qs = sp.toString();
      const expected = qs ? `?${qs}` : "";
      if (locationRef.current.search !== expected) {
        navigate(`${locationRef.current.pathname}${expected || ""}`, { replace: true });
      }
      return nextBulk;
    });
  }, [bulkSelection, sectionId, navigate]);
  const [bulkProgress, setBulkProgress] = useState<BulkRunnerProgress | null>(null);
  const [bulkResults, setBulkResults] = useState<BulkActionResultItem<number>[]>([]);
  const [bulkResultsOpen, setBulkResultsOpen] = useState(false);
  const [bulkSummary, setBulkSummary] = useState<BulkActionSummary | null>(null);
  // groupPanelTasks removed, using actionDialog.tasks instead
  const bulkExecuting = bulkProgress?.running ?? false;

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
    enabled: !!me?.id,
    retry: false,
  });

  const lockedSection = useMemo(() => {
    if (!isSingleWindow || !sections || lockedSectionId === null) return null;
    return sections.find((s) => s.id === lockedSectionId && s.is_active) || null;
  }, [isSingleWindow, sections, lockedSectionId]);
  const isSingleWindowBlocked = isSingleWindow && !lockedSection;

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
    const validParam = Number.isFinite(paramId) ? sections.find((s) => s.id === paramId) : null;
    if (validParam) {
      if (sectionId !== validParam.id) setSectionId(validParam.id);
      return;
    }
    const first = sections.find((s) => s.is_active) || sections[0];
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

  const { data: board, isLoading: boardLoading } = useQuery({
    queryKey: ["shopfloor-board", sectionId, boardParams, requestOptions?.singleSectionLockId ?? null],
    queryFn: () => getSectionBoard(sectionId as number, boardParams, requestOptions),
    enabled: sectionId !== null && !!me?.id && !isSingleWindowBlocked,
    retry: false,
  });

  const { data: stats } = useQuery({
    queryKey: ["shopfloor-stats", sectionId, dateFrom, dateTo, requestOptions?.singleSectionLockId ?? null],
    queryFn: () =>
      getSectionDailyStats(sectionId as number, {
        date_from: `${dateFrom}T00:00:00`,
        date_to: `${dateTo}T23:59:59`,
      }, requestOptions),
    enabled: sectionId !== null && !!me?.id && !!dateFrom && !!dateTo && !isSingleWindow && !isSingleWindowBlocked,
    retry: false,
  });

  const pushActionLog = useCallback((_payload: any) => {}, []);

  const invalidateShopfloor = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.shopfloor.board(sectionId as number) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.shopfloor.stats(sectionId as number) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.shopfloor.incomingTransfers(sectionId as number) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.shopfloor.summary() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.transfers.readyAll() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.transfers.historyAll() });
    void queryClient.invalidateQueries({ queryKey: ["auditLogs"] });
  }, [queryClient, sectionId]);

  const openActionDialog = useCallback((_type: TaskActionDialogType, task: SectionBoardTask) => {
    const now = nowLocalDateTimeParts();
    setActionDialog({ open: true, type: "complete", task, tasks: null });
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
      e.preventDefault();
      if (isSingleWindow) {
        const now = Date.now();
        if (now - lastEscapeAtRef.current < DOUBLE_ESCAPE_TIMEOUT_MS) {
          if (resetTimer) {
            clearTimeout(resetTimer);
            resetTimer = null;
          }
          lastEscapeAtRef.current = 0;
          activatedSingleWindowRef.current = false;
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
        toggleBulkMode();
      }
    };
    window.addEventListener("keydown", handler);
    return () => {
      window.removeEventListener("keydown", handler);
      if (resetTimer) clearTimeout(resetTimer);
    };
  }, [
    bulkMode,
    isSingleWindow,
    actionDialog.open,
    bulkResultsOpen,
    navigate,
    sectionId,
    toggleBulkMode,
  ]);

  const closeActionDrawer = useCallback(() => {
    setActionDialog({ open: false, type: "complete", task: null, tasks: null });
  }, []);

  const groupCompleteMutation = useMutation({
    mutationFn: ({ entries }: { entries: Parameters<typeof bulkCompleteTasks>[0]; tasks?: SectionBoardTask[] }) =>
      bulkCompleteTasks(entries, requestOptions),
    onSuccess: (response, variables) => {
      const tasks = variables.tasks || [];
      const summary = summarizeBulkResults(response.results.map(r => ({ id: r.id, status: r.status, reason: r.reason })));
      const totalGood = variables.entries.reduce((sum, e) => sum + toInteger(e.good_quantity), 0);
      const totalDefect = variables.entries.reduce((sum, e) => sum + toInteger(e.defect_quantity || "0"), 0);

      const sectionInfo = selectedSection ? `на участке "${selectedSection.name}" (${selectedSection.code})` : "";
      const taskInfo = tasks.length > 0
        ? `для операций: ${tasks.map(t => t.operation_name || t.operation_code).filter(Boolean).join(", ")}`
        : "";

      if (summary.failed > 0) {
        toast({
          title: "Частичный успех",
          description: `${summary.success} успешно, ${summary.failed} ошибок`,
          variant: "destructive",
        });
        setConflictHint(`Не удалось завершить часть задач: ${response.results.filter(r => r.status === "failed").map(r => r.reason).join(", ")}`);
        
        pushActionLog({
          status: "info",
          title: "Групповое подтверждение (частично)",
          message: `Подтверждено в группе: годные = ${totalGood} шт., брак = ${totalDefect} шт. ${sectionInfo} ${taskInfo}. Успешно: ${summary.success}, ошибок: ${summary.failed}.`,
          taskIds: tasks.map(t => t.id),
          productSku: Array.from(new Set(tasks.map(t => t.display_sku || t.product_sku).filter(Boolean))).join(", "),
          operationName: Array.from(new Set(tasks.map(t => t.operation_name || t.operation_code).filter(Boolean))).join(", "),
          qtyText: `годн: ${totalGood}, брак: ${totalDefect}`,
          comment: variables.entries[0]?.comment || undefined,
          errorDetails: `Не удалось завершить часть задач: ${response.results.filter(r => r.status === "failed").map(r => r.reason).join(", ")}`,
        });
      } else {
        toast({ title: "Группа завершена", variant: "success" });
        pushActionLog({
          status: "success",
          title: "Группа подтверждена",
          message: `Группа из ${response.results.length} задач успешно подтверждена ${sectionInfo} ${taskInfo}. Подтверждено всего: годные = ${totalGood} шт., брак = ${totalDefect} шт.`,
          taskIds: tasks.map(t => t.id),
          productSku: Array.from(new Set(tasks.map(t => t.display_sku || t.product_sku).filter(Boolean))).join(", "),
          operationName: Array.from(new Set(tasks.map(t => t.operation_name || t.operation_code).filter(Boolean))).join(", "),
          qtyText: `годн: ${totalGood}, брак: ${totalDefect}`,
          comment: variables.entries[0]?.comment || undefined,
        });
        closeActionDrawer();
        setConflictHint(null);
      }
      invalidateShopfloor();
    },
    onError: (err, variables) => {
      const message = getErrorMessage(err);
      const tasks = variables.tasks || [];
      const taskInfo = tasks.length > 0
        ? `для операций: ${tasks.map(t => t.operation_name || t.operation_code).filter(Boolean).join(", ")}`
        : "";
      const sectionInfo = selectedSection ? `на участке "${selectedSection.name}" (${selectedSection.code})` : "";

      toast({ title: "Ошибка завершения группы", description: message, variant: "destructive" });
      pushActionLog({
        status: "error",
        title: "Ошибка завершения группы",
        message: `Не удалось подтвердить группу задач ${sectionInfo} ${taskInfo}. Причина: ${message}`,
        taskIds: tasks.map(t => t.id),
        productSku: Array.from(new Set(tasks.map(t => t.display_sku || t.product_sku).filter(Boolean))).join(", "),
        operationName: Array.from(new Set(tasks.map(t => t.operation_name || t.operation_code).filter(Boolean))).join(", "),
        errorDetails: message,
      });
      setConflictHint(message);
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
      invalidateShopfloor();
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

  const pendingMutation =
    completeMutation.isPending ||
    groupCompleteMutation.isPending;

  const submitAction = useCallback(() => {
    const task = actionDialog.task;
    const tasks = actionDialog.tasks;
    const isGroup = !!tasks && tasks.length > 0;
    if (!task && !isGroup) return;

    const qty = toInteger(actionQty || "0");
    const effectivePerformedAt = `${performedDate}T${performedShift === "1" ? "08:00" : "20:00"}`;
    const effectiveAccountedAt = nowLocalDateTime();
    const executorUserId = me?.id;

    const good = qty;
    const defect = toInteger(defectQty || "0");
    if (good + defect <= 0) {
      toast({ title: "Ошибка", description: "Укажите факт или брак", variant: "destructive" });
      setConflictHint("Укажите хотя бы одно количество: годные или брак.");
      return;
    }

    const inWork = isGroup
      ? tasks.reduce((sum, t) => sum + toInteger(t.cache.in_work_quantity), 0)
      : toInteger(task!.cache.in_work_quantity);

    if (inWork > 0 && good + defect > inWork) {
      setConflictHint(
        isGroup
          ? `Сумма факта и брака больше общего объема в работе всей группы (${fmtQty(String(inWork))}).`
          : `Сумма факта и брака больше объема в работе (${fmtQty(String(inWork))}).`
      );
      return;
    }

    if (isGroup) {
      const entries: Parameters<typeof bulkCompleteTasks>[0] = [];

      // Заполняем задачи по порядку, пока не израсходуем good/defect.
      // Не пропускаем задачи с in_work=0 — бэкенд сделает auto-issue, если задача
      // в статусе ready.
      if (good > 0 || defect > 0) {
        let remainingGood = good;
        let remainingDefect = defect;

        for (let i = 0; i < tasks.length; i++) {
          const t = tasks[i];
          const capacity = Math.max(0, toInteger(t.planned_quantity));

          // good: минимум из остатка, planned_quantity и in_work (если in_work>0)
          const tInWork = toInteger(t.cache.in_work_quantity);
          const goodCapacity = tInWork > 0 ? Math.min(capacity, tInWork) : capacity;
          const goodQty = Math.min(remainingGood, goodCapacity);
          remainingGood -= goodQty;

          // defect: до remaining, лимит — capacity - goodQty (или tInWork - goodQty при tInWork>0)
          const defectLimit = tInWork > 0 ? Math.max(0, tInWork - goodQty) : Math.max(0, capacity - goodQty);
          const defectQty = Math.min(remainingDefect, defectLimit);
          remainingDefect -= defectQty;

          if (goodQty > 0 || defectQty > 0) {
            entries.push({
              task_id: t.id,
              good_quantity: String(goodQty),
              defect_quantity: String(defectQty),
              comment: actionComment || undefined,
              idempotency_key: makeIdempotencyKey(`complete-${t.id}`),
              executor_user_id: executorUserId,
              performed_at: effectivePerformedAt,
              accounted_at: effectiveAccountedAt,
            });
          }

          if (remainingGood <= 0 && remainingDefect <= 0) break;
        }
      }

      groupCompleteMutation.mutate({ entries, tasks: tasks });
    } else {
      completeMutation.mutate({
        taskId: task!.id,
        task: task!,
        payload: {
          good_quantity: String(good),
          defect_quantity: String(defect),
          comment: actionComment || undefined,
          idempotency_key: makeIdempotencyKey("complete"),
          executor_user_id: executorUserId,
          performed_at: effectivePerformedAt,
          accounted_at: effectiveAccountedAt,
        },
      });
    }
  }, [
    actionDialog,
    actionQty,
    performedDate,
    performedShift,
    me?.id,
    completeMutation,
    groupCompleteMutation,
    actionComment,
    defectQty,
  ]);

  const finishBulk = useCallback((
    results: BulkActionResultItem<number>[],
    totalGood?: number,
    totalDefect?: number
  ) => {
    const summary = summarizeBulkResults(results);
    setBulkResults(results);
    setBulkSummary(summary);
    if (summary.failed > 0) setBulkResultsOpen(true);
    setBulkProgress(null);

    const sectionInfo = selectedSection ? `на участке "${selectedSection.name}" (${selectedSection.code})` : "";
    const qtyInfo = (totalGood !== undefined || totalDefect !== undefined)
      ? ` (введено всего: годные = ${totalGood || 0} шт., брак = ${totalDefect || 0} шт.)`
      : "";

    const matchedTasks = results
      .map((r) => board?.tasks?.find((t) => t.id === r.id))
      .filter(Boolean) as SectionBoardTask[];

    const productSkus = Array.from(new Set(matchedTasks.map((t) => t.display_sku || t.product_sku).filter(Boolean))).join(", ");
    const operationNames = Array.from(new Set(matchedTasks.map((t) => t.operation_name || t.operation_code).filter(Boolean))).join(", ");

    pushActionLog({
      status: summary.failed > 0 ? (summary.success > 0 ? "info" : "error") : "success",
      title: "Массовое подтверждение",
      message: `Массовое подтверждение ${sectionInfo}: успешно завершено задач: ${summary.success}, ошибок: ${summary.failed}${qtyInfo}.`,
      taskIds: results.map((r) => r.id),
      productSku: productSkus || undefined,
      operationName: operationNames || undefined,
      qtyText: (totalGood !== undefined || totalDefect !== undefined)
        ? `годн: ${totalGood || 0}, брак: ${totalDefect || 0}`
        : undefined,
    });

    // Don't clear selection — user should see the result
    toast({
      title: summary.failed > 0 ? "Частичный успех" : "Массовая операция",
      description: `${summary.success} успешно, ${summary.failed} ошибок${summary.skipped > 0 ? `, ${summary.skipped} пропущено` : ""}`,
      variant: summary.failed > 0 ? "destructive" : "success",
    });
  }, [bulkSelection, pushActionLog, selectedSection, board]);

  // Bulk operations via panel
  const handleBulkComplete = useCallback(async (entries: { taskId: number; goodQty: string; defectQty: string }[]) => {
    setBulkProgress({ total: entries.length, completed: 0, running: true });
    const lockOptions = lockedSectionId !== null ? { singleSectionLockId: lockedSectionId } : undefined;
    
    const totalGood = entries.reduce((sum, e) => sum + toInteger(e.goodQty), 0);
    const totalDefect = entries.reduce((sum, e) => sum + toInteger(e.defectQty), 0);

    try {
      const response = await bulkCompleteTasks(
        entries.map((entry) => ({
          task_id: entry.taskId,
          good_quantity: entry.goodQty,
          defect_quantity: entry.defectQty || "0",
          idempotency_key: makeIdempotencyKey("bulk-complete"),
          executor_user_id: me?.id,
          performed_at: nowLocalDateTime(),
          accounted_at: nowLocalDateTime(),
        })),
        lockOptions,
      );
      const results: BulkActionResultItem<number>[] = response.results.map((r) => ({
        id: r.id,
        status: r.status,
        reason: r.reason,
      }));
      finishBulk(results, totalGood, totalDefect);
    } catch (e) {
      const reason = getErrorMessage(e);
      finishBulk(entries.map((entry) => ({ id: entry.taskId, status: "failed" as const, reason })), totalGood, totalDefect);
    }
  }, [me?.id, lockedSectionId, finishBulk]);

  const handleBulkExecuteAll = useCallback(async (data: {
    completeEntries: { taskId: number; goodQty: string; defectQty: string }[];
    performedAt?: string;
    accountedAt?: string;
  }) => {
    const total = data.completeEntries.length;
    const lockOptions = lockedSectionId !== null ? { singleSectionLockId: lockedSectionId } : undefined;
    setBulkProgress({ total, completed: 0, running: true });
    const allResults: BulkActionResultItem<number>[] = [];

    const effectivePerformedAt = data.performedAt || nowLocalDateTime();
    const effectiveAccountedAt = data.accountedAt || effectivePerformedAt;

    const totalGood = data.completeEntries.reduce((sum, e) => sum + toInteger(e.goodQty), 0);
    const totalDefect = data.completeEntries.reduce((sum, e) => sum + toInteger(e.defectQty), 0);

    if (data.completeEntries.length > 0) {
      try {
        const response = await bulkCompleteTasks(
          data.completeEntries.map((entry) => ({
            task_id: entry.taskId,
            good_quantity: entry.goodQty,
            defect_quantity: entry.defectQty,
            idempotency_key: makeIdempotencyKey("bulk-complete"),
            executor_user_id: me?.id,
            performed_at: effectivePerformedAt,
            accounted_at: effectiveAccountedAt,
          })),
          lockOptions,
        );
        for (const r of response.results) {
          allResults.push({ id: r.id, status: r.status, reason: r.reason });
        }
      } catch (e) {
        const reason = getErrorMessage(e);
        for (const entry of data.completeEntries) {
          allResults.push({ id: entry.taskId, status: "failed", reason });
        }
      }
    }

    invalidateShopfloor();
    setBulkProgress({ total, completed: total, running: false });
    finishBulk(allResults, totalGood, totalDefect);
  }, [me?.id, lockedSectionId, invalidateShopfloor, finishBulk]);

  // Завершить группу: открывает боковую панель завершения группы
  const handleCompleteGroup = useCallback((group: TaskGroup) => {
    const now = nowLocalDateTimeParts();
    setActionDialog({ open: true, type: "complete", task: null, tasks: group.tasks });
    setPerformedDate(now.date);
    setPerformedShift("1");
    setActionComment("");
    setConflictHint(null);
    setActionQty("");
    setDefectQty("");
  }, []);


  const tasks = board?.tasks || [];
  const selectedTasks = useMemo(
    () => tasks.filter((t) => bulkSelection.selectedIds.has(t.id)),
    [tasks, bulkSelection.selectedIds],
  );

  const handleSelectAll = useCallback((ids: number[]) => {
    bulkSelection.selectAll(ids);
  }, [bulkSelection]);





  const canToggleSingleWindow = sectionId !== null && !isSingleWindowBlocked;
  const selectedSectionColor = selectedSection?.icon_color || "#1D4ED8";
  const selectedSectionTint = selectedSectionColor.startsWith("#") ? `${selectedSectionColor}1A` : "#DBEAFE";

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
        {selectedSection && (
          <div
            className="rounded-xl border px-4 py-3"
            style={{ borderColor: selectedSectionColor, backgroundColor: selectedSectionTint }}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-3 min-w-0">
                {isSingleWindow ? (
                  <SectionSwitcherTiles
                    sections={(sections || []).filter((s) => s.is_active)}
                    summary={summary?.sections || []}
                    selectedSectionId={sectionId}
                    onSelect={(nextId) => {
                      setSectionId(nextId);
                      navigate(`/section-tasks/${nextId}?singleWindow=1`);
                    }}
                    variant="popover"
                    headerContent={
                      <>
                        <span
                          className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg"
                          style={{ backgroundColor: "#FFFFFFB3", color: selectedSectionColor }}
                        >
                          {selectedSection.icon ? renderIcon(selectedSection.icon, "h-5 w-5") : <span className="h-2.5 w-2.5 rounded-full bg-current" />}
                        </span>
                        <div className="min-w-0">
                          <div className="text-xs font-semibold uppercase tracking-wide" style={{ color: selectedSectionColor }}>
                            {selectedSection.code}
                          </div>
                          <div className="truncate text-xl font-bold leading-tight text-slate-900">
                            {selectedSection.name}
                          </div>
                        </div>
                      </>
                    }
                  />
                ) : (
                  <>
                    <span
                      className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg"
                      style={{ backgroundColor: "#FFFFFFB3", color: selectedSectionColor }}
                    >
                      {selectedSection.icon ? renderIcon(selectedSection.icon, "h-5 w-5") : <span className="h-2.5 w-2.5 rounded-full bg-current" />}
                    </span>
                    <div className="min-w-0">
                      <div className="text-xs font-semibold uppercase tracking-wide" style={{ color: selectedSectionColor }}>
                        {selectedSection.code}
                      </div>
                      <div className="truncate text-xl font-bold leading-tight text-slate-900">
                        {selectedSection.name}
                      </div>
                    </div>
                  </>
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

        {!isSingleWindow && (
          <SectionSwitcherTiles
            sections={(sections || []).filter((section) => section.is_active)}
            summary={summary?.sections || []}
            selectedSectionId={sectionId}
            onSelect={(nextId) => {
              setSectionId(nextId);
              navigate(`/section-tasks/${nextId}`);
            }}
          />
        )}

        {!isSingleWindowBlocked && sectionId && (
          <div className="space-y-4">
            {/* Bulk operations panel */}
            {bulkMode && bulkSelection.selectedCount > 0 && (
              <BulkOperationsPanel
                tasks={selectedTasks}
                onExecuteAll={handleBulkExecuteAll}
                pending={bulkExecuting}
                onDone={() => setBulkMode(false)}
              />
            )}

            {/* Group operations panel (opened by «Завершить группу») is now handled by TaskActionDrawer */}

            <div className="flex flex-wrap items-center gap-2">
              <DateRangePicker
                from={dateRange.from}
                to={dateRange.to}
                onChange={setDateRange}
                className="w-full sm:w-auto sm:min-w-[280px] max-w-md"
              />
              <Button variant="outline" size="sm" onClick={() => setPlanModalOpen(true)}>
                План
              </Button>
            </div>

            <SectionTasksBoard
              tasks={tasks}
              isLoading={boardLoading}
              mode={viewMode}
              onModeChange={setViewMode}
              onAction={openActionDialog}
              bulkMode={bulkMode}
              onBulkModeChange={toggleBulkMode}
              bulkSelection={bulkMode ? bulkSelection : undefined}
              profile={profile}
              onSelectAllVisible={handleSelectAll}
              onCompleteGroup={handleCompleteGroup}
            />



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
                          <tr>
                            <td colSpan={5} className="p-4 text-center text-muted-foreground">Нет данных за период</td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
        )}
      </section>

      <TaskActionDrawer
        open={actionDialog.open}
        onOpenChange={(open) => {
          if (!open) closeActionDrawer();
          else setActionDialog((prev) => ({ ...prev, open }));
        }}
        task={actionDialog.task}
        tasks={actionDialog.tasks}
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
        tasks={tasks}
        availableOperations={board?.available_operations || []}
      />



    </>
  );
}
