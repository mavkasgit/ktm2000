import { useCallback, useEffect, useMemo, useState, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ListChecks } from "lucide-react";

import { apiClient, getErrorMessage } from "@/shared/api/client";
import { listSections } from "@/shared/api/sections";
import {
  acceptTransfer,
  completeTask,
  createTransfer,
  getIncomingTransfers,
  getSectionBoard,
  getSectionDailyStats,
  getSectionsSummary,
  issueTask,
  type AcceptTransferInput,
  type DailyStatsRow,
  type SectionBoardTask,
} from "@/shared/api/shopfloor";
import { DatePicker, renderIcon, toast, Button } from "@/shared/ui";
import { useBulkSelection } from "@/shared/bulk";
import { BulkResultsDialog, summarizeBulkResults, type BulkActionResultItem, type BulkActionSummary, type BulkRunnerProgress } from "@/shared/bulk";
import { IncomingTransfersPanel } from "../components/IncomingTransfersPanel";
import { SectionSwitcherTiles } from "../components/SectionSwitcherTiles";
import { SectionTasksBoard, type TaskActionDialogType, type TaskBoardViewMode } from "../components/SectionTasksBoard";
import { TaskActionDrawer } from "../components/TaskActionDrawer";
import { BulkOperationsPanel } from "../components/BulkOperationsPanel";

type MeResponse = {
  id: number;
  email: string;
  full_name: string;
  role: "admin" | "planner" | "section_manager" | "operator" | "viewer";
  section_id: number | null;
  is_active: boolean;
};

type ActionLogEntry = {
  id: string;
  title: string;
  status: "success" | "error" | "info";
  message: string;
  createdAt: string;
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
  const [viewMode, setViewMode] = useState<TaskBoardViewMode>("active");
  const [dateFrom, setDateFrom] = useState<string>("");
  const [dateTo, setDateTo] = useState<string>("");
  const [conflictHint, setConflictHint] = useState<string | null>(null);
  const [actionLog, setActionLog] = useState<ActionLogEntry[]>([]);

  const [actionDialog, setActionDialog] = useState<{ open: boolean; type: TaskActionDialogType; task: SectionBoardTask | null }>({
    open: false,
    type: "complete",
    task: null,
  });
  const [actionQty, setActionQty] = useState("");
  const [defectQty, setDefectQty] = useState("");
  const [timesMatch, setTimesMatch] = useState(true);
  const [performedDate, setPerformedDate] = useState("");
  const [performedTime, setPerformedTime] = useState("");
  const [accountedDate, setAccountedDate] = useState("");
  const [accountedTime, setAccountedTime] = useState("");
  const [dateToday, setDateToday] = useState(true);
  const [actionComment, setActionComment] = useState("");

  // Bulk mode state
  const [bulkMode, setBulkMode] = useState(searchParams.get("bulk") === "1" || searchParams.get("singleWindow") === "1");
  const bulkSelection = useBulkSelection<number>();
  const activatedSingleWindowRef = useRef(false);
  const locationRef = useRef(location);
  locationRef.current = location;

  const toggleBulkMode = useCallback(() => {
    setBulkMode((prev) => {
      const nextBulk = !prev;
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
  const bulkExecuting = bulkProgress?.running ?? false;

  const { data: me } = useQuery({
    queryKey: ["auth-me"],
    queryFn: async () => (await apiClient.get<MeResponse>("/auth/me")).data,
    retry: false,
  });

  const { data: sections } = useQuery({
    queryKey: ["sections"],
    queryFn: listSections,
  });

  const { data: summary } = useQuery({
    queryKey: ["shopfloor-sections-summary"],
    queryFn: getSectionsSummary,
    enabled: !!me?.id && !isSingleWindow,
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
      const expectedPath = `/shopfloor-tasks/${activeLockedSection.id}`;
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
    navigate(`/shopfloor-tasks/${first.id}`, { replace: true });
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

  const { data: incomingTransfersData, isLoading: incomingLoading } = useQuery({
    queryKey: ["shopfloor-incoming-transfers", sectionId, requestOptions?.singleSectionLockId ?? null],
    queryFn: () => getIncomingTransfers(sectionId as number, requestOptions),
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

  const pushActionLog = useCallback((entry: Omit<ActionLogEntry, "id" | "createdAt">) => {
    setActionLog((prev) => {
      const next = [
        {
          id: `${Date.now()}-${Math.floor(Math.random() * 10000)}`,
          createdAt: new Date().toISOString(),
          ...entry,
        },
        ...prev,
      ];
      return next.slice(0, 10);
    });
  }, []);

  const invalidateShopfloor = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["shopfloor-board"] });
    queryClient.invalidateQueries({ queryKey: ["shopfloor-stats"] });
    queryClient.invalidateQueries({ queryKey: ["shopfloor-incoming-transfers"] });
    queryClient.invalidateQueries({ queryKey: ["shopfloor-sections-summary"] });
  }, [queryClient]);

  const closeActionDrawer = useCallback(() => {
    setActionDialog({ open: false, type: "complete", task: null });
  }, []);

  const issueMutation = useMutation({
    mutationFn: ({ taskId, payload }: { taskId: number; payload: Parameters<typeof issueTask>[1] }) =>
      issueTask(taskId, payload, requestOptions),
    onSuccess: () => {
      toast({ title: "Выдача записана", variant: "success" });
      pushActionLog({ status: "success", title: "Выдача", message: "Операция успешно записана." });
      invalidateShopfloor();
      closeActionDrawer();
      setConflictHint(null);
    },
    onError: (err) => {
      const message = getErrorMessage(err);
      toast({ title: "Ошибка", description: message, variant: "destructive" });
      pushActionLog({ status: "error", title: "Выдача", message });
      setConflictHint(conflictHintFromError(message));
    },
  });

  const completeMutation = useMutation({
    mutationFn: ({ taskId, payload }: { taskId: number; payload: Parameters<typeof completeTask>[1] }) =>
      completeTask(taskId, payload, requestOptions),
    onSuccess: () => {
      toast({ title: "Факт сохранен", variant: "success" });
      pushActionLog({ status: "success", title: "Факт", message: "Фактическое выполнение сохранено." });
      invalidateShopfloor();
      closeActionDrawer();
      setConflictHint(null);
    },
    onError: (err) => {
      const message = getErrorMessage(err);
      toast({ title: "Ошибка", description: message, variant: "destructive" });
      pushActionLog({ status: "error", title: "Факт", message });
      setConflictHint(conflictHintFromError(message));
    },
  });

  const sendMutation = useMutation({
    mutationFn: (payload: Parameters<typeof createTransfer>[0]) => createTransfer(payload, requestOptions),
    onSuccess: () => {
      toast({ title: "Передача отправлена", variant: "success" });
      pushActionLog({ status: "success", title: "Передача", message: "Передача на следующий этап отправлена." });
      invalidateShopfloor();
      closeActionDrawer();
      setConflictHint(null);
    },
    onError: (err) => {
      const message = getErrorMessage(err);
      toast({ title: "Ошибка", description: message, variant: "destructive" });
      pushActionLog({ status: "error", title: "Передача", message });
      setConflictHint(conflictHintFromError(message));
    },
  });

  const acceptTransferMutation = useMutation({
    mutationFn: ({ transferId, payload }: { transferId: number; payload: AcceptTransferInput }) =>
      acceptTransfer(transferId, payload, requestOptions),
    onSuccess: (result) => {
      const status = result.status === "accepted" ? "Принято полностью" : result.status === "partially_accepted" ? "Принято частично" : "Отклонено";
      toast({ title: "Входящая передача обновлена", description: status, variant: "success" });
      pushActionLog({ status: "success", title: "Приемка", message: `Передача #${result.transfer_id}: ${status}.` });
      invalidateShopfloor();
    },
    onError: (err) => {
      const message = getErrorMessage(err);
      toast({ title: "Ошибка приемки", description: message, variant: "destructive" });
      pushActionLog({ status: "error", title: "Приемка", message });
    },
  });

  const openActionDialog = useCallback((type: TaskActionDialogType, task: SectionBoardTask) => {
    const now = nowLocalDateTimeParts();
    setActionDialog({ open: true, type, task });
    setTimesMatch(true);
    setDateToday(true);
    setPerformedDate(now.date);
    setPerformedTime(now.time);
    setAccountedDate(now.date);
    setAccountedTime(now.time);
    setActionComment("");
    setConflictHint(null);
    if (type === "complete") {
      setActionQty("");
      setDefectQty("");
    } else if (type === "issue") {
      setActionQty(fmtQty(task.cache.remaining_quantity));
      setDefectQty("");
    } else {
      const transferable = Math.max(0, toInteger(task.cache.completed_quantity) - toInteger(task.cache.transferred_quantity));
      setActionQty(Number.isFinite(transferable) ? String(transferable) : "");
      setDefectQty("");
    }
  }, []);

  const handleTimesMatchChange = useCallback(
    (checked: boolean) => {
      setTimesMatch(checked);
      if (checked) {
        setAccountedDate(performedDate);
        setAccountedTime(performedTime);
      }
    },
    [performedDate, performedTime]
  );

  useEffect(() => {
    if (!timesMatch) return;
    setAccountedDate(performedDate);
    setAccountedTime(performedTime);
  }, [timesMatch, performedDate, performedTime]);

  useEffect(() => {
    if (!dateToday) return;
    const today = nowLocalDateTimeParts().date;
    if (performedDate !== today) {
      setPerformedDate(today);
    }
    if (accountedDate !== today) {
      setAccountedDate(today);
    }
  }, [dateToday, performedDate, accountedDate]);

  // Escape key to exit bulk mode
  useEffect(() => {
    if (!bulkMode) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        toggleBulkMode();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [bulkMode, toggleBulkMode]);

  const submitAction = useCallback(() => {
    const task = actionDialog.task;
    if (!task) return;

    const qty = toInteger(actionQty || "0");
    const toIsoDateTime = (dateStr: string, timeStr: string): string => {
      if (!timeStr) return nowLocalDateTime();
      if (!dateStr) {
        const d = new Date();
        const p = (v: number) => String(v).padStart(2, "0");
        const today = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
        return `${today}T${timeStr}`;
      }
      if (/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) {
        return `${dateStr}T${timeStr}`;
      }
      const [dd, mm, yyyy] = dateStr.split(".");
      const [hh, min] = timeStr.split(":");
      if (!dd || !mm || !yyyy || !hh || !min) return nowLocalDateTime();
      return `${yyyy}-${mm}-${dd}T${hh}:${min}`;
    };
    const effectivePerformedAt = toIsoDateTime(performedDate, performedTime);
    const effectiveAccountedAt = toIsoDateTime(accountedDate, accountedTime) || effectivePerformedAt;
    const executorUserId = me?.id;

    if (!(qty > 0)) {
      toast({ title: "Ошибка", description: "Количество должно быть больше 0", variant: "destructive" });
      setConflictHint("Укажите количество больше нуля.");
      return;
    }

    if (actionDialog.type === "issue") {
      const maxIssue = toInteger(task.cache.available_quantity);
      if (Number.isFinite(maxIssue) && qty > maxIssue) {
        setConflictHint(`Количество больше доступного (${fmtQty(String(maxIssue))}).`);
        return;
      }
      issueMutation.mutate({
        taskId: task.id,
        payload: {
          quantity: String(qty),
          comment: actionComment || undefined,
          idempotency_key: makeIdempotencyKey("issue"),
          executor_user_id: executorUserId,
          performed_at: effectivePerformedAt,
          accounted_at: effectiveAccountedAt,
        },
      });
      return;
    }

    if (actionDialog.type === "complete") {
      const parsedDefect = toInteger(defectQty || "0");
      const good = qty;
      const defect = Number.isFinite(parsedDefect) ? parsedDefect : 0;
      if (good + defect <= 0) {
        toast({ title: "Ошибка", description: "Укажите факт или брак", variant: "destructive" });
        setConflictHint("Укажите хотя бы одно количество: годные или брак.");
        return;
      }
      const inWork = toInteger(task.cache.in_work_quantity);
      if (Number.isFinite(inWork) && good + defect > inWork) {
        setConflictHint(`Сумма факта и брака больше объема в работе (${fmtQty(String(inWork))}).`);
        return;
      }
      completeMutation.mutate({
        taskId: task.id,
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
      return;
    }

    if (!task.next_operation_name) {
      const message = "Финальный этап маршрута: передача на следующий этап не требуется.";
      toast({ title: "Передача недоступна", description: message, variant: "destructive" });
      setConflictHint(message);
      return;
    }

    const transferable = Math.max(0, toInteger(task.cache.completed_quantity) - toInteger(task.cache.transferred_quantity));
    if (Number.isFinite(transferable) && qty > transferable) {
      setConflictHint(`Количество передачи больше доступного (${fmtQty(String(transferable))}).`);
      return;
    }
    sendMutation.mutate({
      from_task_id: task.id,
      quantity: String(qty),
      comment: actionComment || undefined,
      idempotency_key: makeIdempotencyKey("send"),
      executor_user_id: executorUserId,
      performed_at: effectivePerformedAt,
      accounted_at: effectiveAccountedAt,
    });
  }, [
    actionDialog,
    actionQty,
    performedDate,
    performedTime,
    accountedDate,
    accountedTime,
    me?.id,
    issueMutation,
    completeMutation,
    sendMutation,
    actionComment,
    defectQty,
  ]);

  // Bulk operations via panel
  const handleBulkIssue = useCallback(async (entries: { taskId: number; quantity: string }[]) => {
    setBulkProgress({ total: entries.length, completed: 0, running: true });
    const results: BulkActionResultItem<number>[] = [];
    for (let i = 0; i < entries.length; i++) {
      const entry = entries[i];
      try {
        await issueMutation.mutateAsync({
          taskId: entry.taskId,
          payload: {
            quantity: entry.quantity,
            idempotency_key: makeIdempotencyKey("bulk-issue"),
            executor_user_id: me?.id,
            performed_at: nowLocalDateTime(),
            accounted_at: nowLocalDateTime(),
          },
        });
        results.push({ id: entry.taskId, status: "success" });
      } catch (e) {
        results.push({ id: entry.taskId, status: "failed", reason: getErrorMessage(e) });
      }
      setBulkProgress({ total: entries.length, completed: i + 1, running: i + 1 < entries.length });
    }
    finishBulk(results);
  }, [issueMutation, me?.id, invalidateShopfloor]);

  const handleBulkComplete = useCallback(async (entries: { taskId: number; goodQty: string; defectQty: string }[]) => {
    setBulkProgress({ total: entries.length, completed: 0, running: true });
    const results: BulkActionResultItem<number>[] = [];
    for (let i = 0; i < entries.length; i++) {
      const entry = entries[i];
      try {
        await completeMutation.mutateAsync({
          taskId: entry.taskId,
          payload: {
            good_quantity: entry.goodQty,
            defect_quantity: entry.defectQty || "0",
            idempotency_key: makeIdempotencyKey("bulk-complete"),
            executor_user_id: me?.id,
            performed_at: nowLocalDateTime(),
            accounted_at: nowLocalDateTime(),
          },
        });
        results.push({ id: entry.taskId, status: "success" });
      } catch (e) {
        results.push({ id: entry.taskId, status: "failed", reason: getErrorMessage(e) });
      }
      setBulkProgress({ total: entries.length, completed: i + 1, running: i + 1 < entries.length });
    }
    finishBulk(results);
  }, [completeMutation, me?.id, invalidateShopfloor]);

  const handleBulkSend = useCallback(async (entries: { taskId: number; quantity: string }[]) => {
    setBulkProgress({ total: entries.length, completed: 0, running: true });
    const results: BulkActionResultItem<number>[] = [];
    for (let i = 0; i < entries.length; i++) {
      const entry = entries[i];
      try {
        await sendMutation.mutateAsync({
          from_task_id: entry.taskId,
          quantity: entry.quantity,
          idempotency_key: makeIdempotencyKey("bulk-send"),
          executor_user_id: me?.id,
          performed_at: nowLocalDateTime(),
          accounted_at: nowLocalDateTime(),
        });
        results.push({ id: entry.taskId, status: "success" });
      } catch (e) {
        results.push({ id: entry.taskId, status: "failed", reason: getErrorMessage(e) });
      }
      setBulkProgress({ total: entries.length, completed: i + 1, running: i + 1 < entries.length });
    }
    finishBulk(results);
  }, [sendMutation, me?.id, invalidateShopfloor]);

  const finishBulk = useCallback((results: BulkActionResultItem<number>[]) => {
    const summary = summarizeBulkResults(results);
    setBulkResults(results);
    setBulkSummary(summary);
    if (summary.failed > 0) setBulkResultsOpen(true);
    setBulkProgress(null);
    bulkSelection.clear();
    invalidateShopfloor();
    toast({
      title: summary.failed > 0 ? "Частичный успех" : "Массовая операция",
      description: `${summary.success} успешно, ${summary.failed} ошибок${summary.skipped > 0 ? `, ${summary.skipped} пропущено` : ""}`,
      variant: summary.failed > 0 ? "destructive" : "success",
    });
  }, [bulkSelection, invalidateShopfloor]);

  const handleBulkExecuteAll = useCallback(async (data: {
    issueEntries: { taskId: number; quantity: string }[];
    completeEntries: { taskId: number; goodQty: string; defectQty: string }[];
    sendEntries: { taskId: number; quantity: string }[];
  }) => {
    const allResults: BulkActionResultItem<number>[] = [];
    let total = data.issueEntries.length + data.completeEntries.length + data.sendEntries.length;

    // Step 1: Issue
    if (data.issueEntries.length > 0) {
      setBulkProgress({ total, completed: 0, running: true });
      for (let i = 0; i < data.issueEntries.length; i++) {
        const entry = data.issueEntries[i];
        try {
          await issueMutation.mutateAsync({
            taskId: entry.taskId,
            payload: {
              quantity: entry.quantity,
              idempotency_key: makeIdempotencyKey("bulk-issue"),
              executor_user_id: me?.id,
              performed_at: nowLocalDateTime(),
              accounted_at: nowLocalDateTime(),
            },
          });
          allResults.push({ id: entry.taskId, status: "success" });
        } catch (e) {
          allResults.push({ id: entry.taskId, status: "failed", reason: getErrorMessage(e) });
        }
        setBulkProgress({ total, completed: i + 1, running: true });
      }
      invalidateShopfloor();
      // Wait for DB to update
      await new Promise(r => setTimeout(r, 500));
    }

    // Step 2: Complete
    if (data.completeEntries.length > 0) {
      setBulkProgress({ total, completed: data.issueEntries.length, running: true });
      for (let i = 0; i < data.completeEntries.length; i++) {
        const entry = data.completeEntries[i];
        try {
          await completeMutation.mutateAsync({
            taskId: entry.taskId,
            payload: {
              good_quantity: entry.goodQty,
              defect_quantity: entry.defectQty,
              idempotency_key: makeIdempotencyKey("bulk-complete"),
              executor_user_id: me?.id,
              performed_at: nowLocalDateTime(),
              accounted_at: nowLocalDateTime(),
            },
          });
          allResults.push({ id: entry.taskId, status: "success" });
        } catch (e) {
          allResults.push({ id: entry.taskId, status: "failed", reason: getErrorMessage(e) });
        }
        setBulkProgress({ total, completed: data.issueEntries.length + i + 1, running: true });
      }
      invalidateShopfloor();
      // Wait for DB to update
      await new Promise(r => setTimeout(r, 500));
    }

    // Step 3: Send (now completed is in DB)
    if (data.sendEntries.length > 0) {
      setBulkProgress({ total, completed: data.issueEntries.length + data.completeEntries.length, running: true });
      for (let i = 0; i < data.sendEntries.length; i++) {
        const entry = data.sendEntries[i];
        try {
          await sendMutation.mutateAsync({
            from_task_id: entry.taskId,
            quantity: entry.quantity,
            idempotency_key: makeIdempotencyKey("bulk-send"),
            executor_user_id: me?.id,
            performed_at: nowLocalDateTime(),
            accounted_at: nowLocalDateTime(),
          });
          allResults.push({ id: entry.taskId, status: "success" });
        } catch (e) {
          allResults.push({ id: entry.taskId, status: "failed", reason: getErrorMessage(e) });
        }
        setBulkProgress({ total, completed: data.issueEntries.length + data.completeEntries.length + i + 1, running: i + 1 < data.sendEntries.length });
      }
    }

    finishBulk(allResults);
  }, [issueMutation, completeMutation, sendMutation, me?.id, invalidateShopfloor, finishBulk]);

  const handleAcceptTransfer = useCallback(
    (transferId: number, payload: AcceptTransferInput) => {
      acceptTransferMutation.mutate({ transferId, payload });
    },
    [acceptTransferMutation]
  );

  const selectedSection = useMemo(
    () => (sections || []).find((s) => s.id === sectionId) || null,
    [sections, sectionId]
  );

  const pendingMutation = issueMutation.isPending || completeMutation.isPending || sendMutation.isPending;
  const tasks = board?.tasks || [];
  const selectedTasks = useMemo(
    () => tasks.filter((t) => bulkSelection.selectedIds.has(t.id)),
    [tasks, bulkSelection.selectedIds],
  );
  const incomingTransfers = incomingTransfersData?.incoming_transfers || [];
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
                navigate(`/shopfloor-tasks/${sectionId}?singleWindow=1`);
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
                      navigate(`/shopfloor-tasks/${nextId}?singleWindow=1`);
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
                    onClick={() => navigate(sectionId ? `/shopfloor-tasks/${sectionId}` : "/shopfloor-tasks")}
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
                ? "Не задан корректный участок в URL. Откройте /shopfloor-tasks/<id>?singleWindow=1."
                : "Участок не найден или недоступен. Доступ к другим участкам в этом режиме заблокирован."}
            </div>
            <button
              type="button"
              className="mt-3 rounded-md border border-amber-700 px-3 py-1.5 text-xs font-medium hover:bg-amber-100"
              onClick={() => navigate("/shopfloor-tasks")}
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
              navigate(`/shopfloor-tasks/${nextId}`);
            }}
          />
        )}

        {!isSingleWindow && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            <DatePicker value={dateFrom} onChange={setDateFrom} placeholder="Дата от" className="w-full" />
            <DatePicker value={dateTo} onChange={setDateTo} placeholder="Дата до" className="w-full" />
          </div>
        )}

        {!isSingleWindowBlocked && sectionId && (
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
            <div className="xl:col-span-2 space-y-4">
              {/* Bulk mode toggle */}
              <div className="flex items-center gap-2">
                <Button variant="outline" size="sm" onClick={toggleBulkMode}>
                  <ListChecks className="h-4 w-4 mr-1" />
                  {bulkMode ? "Закрыть" : "Групповые операции"}
                </Button>
                {bulkMode && (
                  <span className="text-sm text-muted-foreground">
                    Клик по строке для выбора · Выбрано: {bulkSelection.selectedCount}
                  </span>
                )}
              </div>

              {/* Bulk operations panel */}
              {bulkMode && bulkSelection.selectedCount > 0 && (
                <BulkOperationsPanel
                  tasks={selectedTasks}
                  onExecuteAll={handleBulkExecuteAll}
                  pending={bulkExecuting}
                />
              )}

              <SectionTasksBoard
                tasks={tasks}
                isLoading={boardLoading}
                mode={viewMode}
                onModeChange={setViewMode}
                onAction={openActionDialog}
                bulkMode={bulkMode}
                bulkSelection={bulkMode ? bulkSelection : undefined}
              />

              {!isSingleWindow && (
                <div className="rounded-lg border p-4">
                  <h3 className="text-sm font-semibold mb-3">Журнал действий (сессия)</h3>
                  {actionLog.length === 0 && <div className="text-sm text-muted-foreground">Действий пока нет.</div>}
                  {actionLog.length > 0 && (
                    <div className="space-y-2">
                      {actionLog.map((entry) => (
                        <div key={entry.id} className="rounded-md border px-3 py-2">
                          <div className="flex items-center justify-between gap-2">
                            <div className="font-medium text-sm">{entry.title}</div>
                            <div className="text-xs text-muted-foreground">
                              {new Date(entry.createdAt).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                            </div>
                          </div>
                          <div className={`text-xs mt-1 ${entry.status === "error" ? "text-red-600" : entry.status === "success" ? "text-emerald-700" : "text-muted-foreground"}`}>
                            {entry.message}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

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

            <div className="space-y-4">
              <IncomingTransfersPanel
                transfers={incomingTransfers}
                isLoading={incomingLoading}
                isPending={acceptTransferMutation.isPending}
                onAccept={handleAcceptTransfer}
              />
            </div>
          </div>
        )}
      </section>

      <TaskActionDrawer
        open={actionDialog.open}
        onOpenChange={(open) => {
          if (!open) closeActionDrawer();
          else setActionDialog((prev) => ({ ...prev, open }));
        }}
        type={actionDialog.type}
        task={actionDialog.task}
        actionQty={actionQty}
        setActionQty={setActionQty}
        defectQty={defectQty}
        setDefectQty={setDefectQty}
        timesMatch={timesMatch}
        onTimesMatchChange={handleTimesMatchChange}
        performedDate={performedDate}
        setPerformedDate={setPerformedDate}
        performedTime={performedTime}
        setPerformedTime={setPerformedTime}
        dateToday={dateToday}
        onDateTodayChange={setDateToday}
        accountedDate={accountedDate}
        setAccountedDate={setAccountedDate}
        accountedTime={accountedTime}
        setAccountedTime={setAccountedTime}
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
    </>
  );
}
