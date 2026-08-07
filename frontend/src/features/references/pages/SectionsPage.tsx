import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Plus, ArrowUp, ArrowDown, Settings, X, Pencil, Trash2, Move, Layers, ChevronRight, Warehouse, Factory, Search } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import * as API from "shared/api";
import { usePermission } from "@/features/auth/hooks/usePermission";
import * as SectionsAPI from "shared/api/sections";
import * as ShopfloorAPI from "shared/api/shopfloor";
import * as SpgAPI from "shared/api/spg";
import * as UI from "shared/ui";
import { Button } from "@/shared/ui/button";
import { Badge } from "@/shared/ui/badge";
import { EntityDialog, renderIcon } from "@/shared/ui/EntityDialog";
import { SpgSelect } from "@/shared/ui/SpgSelect";
import { cn } from "@/shared/utils/cn";
import { Popover, PopoverTrigger, PopoverContent } from "@/shared/ui/popover";
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogCancel, AlertDialogAction } from "@/shared/ui/alert-dialog";
import { toast } from "@/shared/ui/use-toast";
import { Input } from "@/shared/ui/input";
import { TablePaginationFooter } from "@/shared/ui/TablePaginationFooter";
import { usePaginatedTableQuery } from "@/shared/hooks/usePaginatedTableQuery";
import type { EntityDialogField } from "@/shared/ui/EntityDialog";
import type { OperationGroup, SectionOperationInfo } from "shared/api/sections";
import { listSectionsPaginated } from "shared/api/sections";
import { queryKeys } from "@/shared/api/queryKeys";
import { sectionTypeLabels } from "@/shared/lib/generated-labels";

type Section = {
  id?: string | number;
  code: string;
  name: string;
  description?: string | null;
  type?: string;
  icon?: string | null;
  icon_color?: string | null;
  sort_order?: number;
  spg_links?: { id: number; code: string; name: string }[];
  operations_count?: number;
};

type Group = {
  spgId: number | "no-spg";
  spgName: string;
  spgIcon: string | null;
  spgIconColor: string | null;
  stocks: Section[];
  productions: Section[];
};

const TYPE_OPTIONS = [
  { value: "production", label: "Производство" },
  { value: "raw_stock", label: "Склад сырья" },
  { value: "wip_stock", label: "Склад полуфабриката" },
  { value: "finished_stock", label: "Склад готовой продукции" },
  { value: "scrap", label: "Брак" },
];

const ui = UI as unknown as Record<string, React.ComponentType<any>>;
const Table = ui.Table ?? "table";

const OP_FIELDS: Record<string, EntityDialogField> = {
  operation_code: { type: "text", label: "Код операции", placeholder: "Введите код", required: true, rowGroup: "row1" },
  operation_name: { type: "text", label: "Название операции", placeholder: "Введите название", required: true, rowGroup: "row1" },
  is_significant: { type: "checkbox", label: "★ Значимая", rowGroup: "row1" },
  icon: { type: "icon", label: "Иконка" },
  icon_color: { type: "color", label: "Цвет" },
};

const GROUP_FIELDS: Record<string, EntityDialogField> = {
  group_code: { type: "text", label: "Код группы", required: true, rowGroup: "row1" },
  group_name: { type: "text", label: "Название группы", required: true, rowGroup: "row1" },
  sort_order: { type: "number", label: "Порядок", min: 0, rowGroup: "row1" },
};

const SECTION_FIELDS: Record<string, EntityDialogField> = {
  code: { type: "text", label: "Код", placeholder: "Введите код", required: true, rowGroup: "row1" },
  name: { type: "text", label: "Название", placeholder: "Введите название", required: true, rowGroup: "row1" },
  type: { type: "select", label: "Тип", required: true, options: TYPE_OPTIONS },
  icon: { type: "icon", label: "Иконка" },
  icon_color: { type: "color", label: "Цвет" },
  description: { type: "text", label: "Описание", placeholder: "Введите описание (необязательно)" },
};

const SPG_FIELDS: Record<string, EntityDialogField> = {
  code: { type: "text", label: "Код", placeholder: "Введите код", required: true, rowGroup: "row1" },
  name: { type: "text", label: "Название", placeholder: "Введите название", required: true, rowGroup: "row1" },
  is_active: { type: "checkbox", label: "Активна", rowGroup: "row1" },
  icon: { type: "icon", label: "Иконка" },
  icon_color: { type: "color", label: "Цвет" },
  description: { type: "text", label: "Описание", placeholder: "Введите описание (необязательно)" },
};

async function apiListSections(params: {
  limit: number;
  offset: number;
  search?: string;
  sort_by?: string;
  sort_order?: "asc" | "desc";
}): Promise<{ items: Section[]; total: number }> {
  const data = await listSectionsPaginated(params);
  return { items: data.items as Section[], total: data.total };
}

async function apiCreateSection(payload: Partial<Section>): Promise<void> {
  const api = API as Record<string, any>;
  if (typeof api.createSection === "function") {
    await api.createSection(payload);
    return;
  }
  const response = await fetch("/api/sections", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`Failed to create section: ${response.status}`);
}

async function apiPatchSection(id: number, payload: Partial<Section>): Promise<void> {
  const api = API as Record<string, any>;
  if (typeof api.patchSection === "function") {
    await api.patchSection(id, payload);
    return;
  }
  const response = await fetch(`/api/sections/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`Failed to update section: ${response.status}`);
}

async function apiDeleteSection(id: number): Promise<void> {
  const api = API as Record<string, any>;
  if (typeof api.deleteSection === "function") {
    await api.deleteSection(id);
    return;
  }
  const response = await fetch(`/api/sections/${id}`, { method: "DELETE" });
  if (!response.ok) {
    let msg = `Failed to delete section: ${response.status}`;
    try {
      const body = await response.json();
      if (body?.detail) msg = body.detail;
    } catch {}
    throw new Error(msg);
  }
}

export function SectionsPage() {
  const { canEditReferences } = usePermission();
  const isReadOnly = !canEditReferences;
  const queryClient = useQueryClient();
  const [items, setItems] = useState<Section[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const {
    page,
    setPage,
    limit,
    setLimit,
    offset,
    getTotalPages,
    getRangeLabel,
  } = usePaginatedTableQuery({
    resetPageDeps: [debouncedSearch],
  });
  const totalPages = getTotalPages(total);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogMode, setDialogMode] = useState<"add" | "edit">("add");
  const [editingItem, setEditingItem] = useState<Section | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [spgs, setSpgs] = useState<SpgAPI.SpgOut[]>([]);
  const [spgDialogOpen, setSpgDialogOpen] = useState(false);
  const [spgDialogMode, setSpgDialogMode] = useState<"add" | "edit">("add");
  const [editingSpg, setEditingSpg] = useState<SpgAPI.SpgOut | null>(null);
  const [deleteSpgDialog, setDeleteSpgDialog] = useState<{ id: number; name: string } | null>(null);

  // Operations panel — now uses groups
  const [expandedSectionId, setExpandedSectionId] = useState<number | null>(null);
  const [expandedSectionName, setExpandedSectionName] = useState<string>("");
  const [opGroups, setOpGroups] = useState<OperationGroup[]>([]);
  const [opsCountById, setOpsCountById] = useState<Record<number, number | undefined>>({});
  const [opsLoading, setOpsLoading] = useState(false);
  const [deleteOpDialog, setDeleteOpDialog] = useState<{ sectionId: number; opId: number; opName: string } | null>(null);
  const [opDialogOpen, setOpDialogOpen] = useState(false);
  const [opDialogMode, setOpDialogMode] = useState<"add" | "edit">("add");
  const [opDialogSectionId, setOpDialogSectionId] = useState<number>(0);
  const [opDialogOpId, setOpDialogOpId] = useState<number>(0);
  const [opDialogInitial, setOpDialogInitial] = useState<Record<string, unknown>>({});
  const [opDialogGroupCode, setOpDialogGroupCode] = useState<string | null>(null);

  // Group dialogs
  const [groupDialogOpen, setGroupDialogOpen] = useState(false);
  const [groupDialogMode, setGroupDialogMode] = useState<"add" | "edit">("add");
  const [groupDialogSectionId, setGroupDialogSectionId] = useState<number>(0);
  const [groupDialogGroupCode, setGroupDialogGroupCode] = useState<string>("");
  const [groupDialogInitial, setGroupDialogInitial] = useState<Record<string, unknown>>({});
  const [deleteGroupDialog, setDeleteGroupDialog] = useState<{ sectionId: number; groupCode: string; groupName: string } | null>(null);

  // Move operation dialog
  const [moveOpDialog, setMoveOpDialog] = useState<{ sectionId: number; opId: number; opName: string; currentGroup: string | null } | null>(null);

  // Единая точка инвалидации связанных кэшей после изменений секций/операций/ГХП.
  const invalidateRelatedCaches = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.sections.all() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.operations.all() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.operationGroups.all() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.spg.all() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.shopfloor.boardAll() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.shopfloor.statsAll() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.shopfloor.summary() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.shopfloor.incomingTransfersAll() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.transfers.readyAll() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.transfers.historyAll() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.spg.snapshotAll() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.routes.all() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.techcards.all() });
  }, [queryClient]);

  const loadOpGroups = useCallback(async (sectionId: number, sectionName: string) => {
    setExpandedSectionId(sectionId);
    setExpandedSectionName(sectionName);
    setOpsLoading(true);
    try {
      const groups = await SectionsAPI.getSectionOperationGroups(sectionId);
      setOpGroups(groups);
      const total = groups.reduce((sum, g) => sum + g.operations.length, 0);
      setOpsCountById((prev) => ({ ...prev, [sectionId]: total }));
    } catch (e) {
      toast({ title: "Ошибка загрузки групп", description: API.getErrorMessage(e), variant: "destructive" });
    } finally {
      setOpsLoading(false);
    }
  }, []);

  const toggleSectionOps = useCallback(async (sectionId: number, sectionName: string) => {
    if (expandedSectionId === sectionId) {
      setExpandedSectionId(null);
      setOpGroups([]);
      return;
    }
    await loadOpGroups(sectionId, sectionName);
  }, [expandedSectionId, loadOpGroups]);

  const toggleOpSignificant = useCallback(async (sectionId: number, opId: number, current: boolean) => {
    try {
      const updated = await ShopfloorAPI.updateSectionOperation(sectionId, opId, { is_significant: !current });
      // Update in groups state
      setOpGroups((prev) => prev.map((g) => ({
        ...g,
        operations: g.operations.map((o) => o.id === opId ? { ...o, is_significant: !current } : o),
      })));
      invalidateRelatedCaches();
    } catch (e) {
      toast({ title: "Ошибка обновления", description: API.getErrorMessage(e), variant: "destructive" });
    }
  }, [invalidateRelatedCaches]);

  const openAddOp = useCallback((sectionId: number, groupCode: string | null) => {
    setOpDialogSectionId(sectionId);
    setOpDialogGroupCode(groupCode);
    setOpDialogMode("add");
    setOpDialogInitial({ operation_code: "", operation_name: "", is_significant: false, icon: "", icon_color: "" });
    setOpDialogOpen(true);
  }, []);

  const openEditOp = useCallback((sectionId: number, op: SectionOperationInfo) => {
    setOpDialogSectionId(sectionId);
    setOpDialogGroupCode(op.group_code);
    setOpDialogMode("edit");
    setOpDialogOpId(op.id);
    setOpDialogInitial({
      operation_code: op.operation_code,
      operation_name: op.operation_name,
      is_significant: op.is_significant,
      icon: op.icon || "",
      icon_color: op.icon_color || "",
    });
    setOpDialogOpen(true);
  }, []);

  const handleSaveOp = useCallback(async (values: Record<string, unknown>) => {
    if (opDialogMode === "add") {
      try {
        const payload = {
          operation_code: String(values.operation_code || ""),
          operation_name: String(values.operation_name || ""),
          is_significant: !!values.is_significant,
          icon: String(values.icon || "") || null,
          icon_color: String(values.icon_color || "") || null,
        };
        const created = await ShopfloorAPI.createSectionOperation(opDialogSectionId, payload);
        // If a group was specified, assign the operation to it
        if (opDialogGroupCode) {
          await SectionsAPI.moveOperation(opDialogSectionId, {
            operation_id: created.id,
            new_group_code: opDialogGroupCode,
          });
          created.group_code = opDialogGroupCode;
          // Find group_name from existing groups
          const grp = opGroups.find((g) => g.group_code === opDialogGroupCode);
          if (grp) created.group_name = grp.group_name;
        }
        // Add to state — find or create the group
        if (opDialogGroupCode) {
          setOpGroups((prev) => prev.map((g) =>
            g.group_code === opDialogGroupCode
              ? { ...g, operations: [...g.operations, created as SectionOperationInfo] }
              : g,
          ));
        } else {
          // Add to "no group" section
          setOpGroups((prev) => {
            const noneGroup = prev.find((g) => g.group_code === null);
            if (noneGroup) {
              return prev.map((g) =>
                g.group_code === null
                  ? { ...g, operations: [...g.operations, created as SectionOperationInfo] }
                  : g,
              );
            }
            return [...prev, { group_code: null, group_name: null, sort_order: 0, operations: [created as SectionOperationInfo] }];
          });
        }
        await invalidateRelatedCaches();
        setOpsCountById((prev) => ({ ...prev, [opDialogSectionId]: (prev[opDialogSectionId] ?? 0) + 1 }));
        setOpDialogOpen(false);
      } catch (e) {
        toast({ title: "Ошибка создания", description: API.getErrorMessage(e), variant: "destructive" });
      }
    } else {
      try {
        const payload = {
          is_significant: !!values.is_significant,
          icon: String(values.icon || "") || null,
          icon_color: String(values.icon_color || "") || null,
        };
        const updated = await ShopfloorAPI.updateSectionOperation(opDialogSectionId, opDialogOpId, payload);
        setOpGroups((prev) => prev.map((g) => ({
          ...g,
          operations: g.operations.map((o) => o.id === opDialogOpId ? { ...o, ...updated } : o),
        })));
        await invalidateRelatedCaches();
        setOpDialogOpen(false);
      } catch (e) {
        toast({ title: "Ошибка обновления", description: API.getErrorMessage(e), variant: "destructive" });
      }
    }
  }, [opDialogMode, opDialogSectionId, opDialogOpId, opDialogGroupCode, opGroups, invalidateRelatedCaches]);

  const deleteOp = useCallback(async (sectionId: number, opId: number, opName: string) => {
    setDeleteOpDialog({ sectionId, opId, opName });
  }, []);

  const confirmedDeleteOp = useCallback(async () => {
    if (!deleteOpDialog) return;
    const { sectionId, opId } = deleteOpDialog;
    try {
      await ShopfloorAPI.deleteSectionOperation(sectionId, opId);
      setOpGroups((prev) => prev.map((g) => ({
        ...g,
        operations: g.operations.filter((o) => o.id !== opId),
      })).filter((g) => g.operations.length > 0 || g.group_code !== null));
      setOpsCountById((prev) => {
        const cur = prev[sectionId] ?? 0;
        return { ...prev, [sectionId]: Math.max(0, cur - 1) };
      });
      await invalidateRelatedCaches();
    } catch (e) {
      toast({ title: "Ошибка удаления", description: API.getErrorMessage(e), variant: "destructive" });
    } finally {
      setDeleteOpDialog(null);
    }
  }, [deleteOpDialog, invalidateRelatedCaches]);

  // Group management
  const openAddGroup = useCallback((sectionId: number) => {
    setGroupDialogSectionId(sectionId);
    setGroupDialogMode("add");
    setGroupDialogGroupCode("");
    setGroupDialogInitial({ group_code: "", group_name: "", sort_order: 0 });
    setGroupDialogOpen(true);
  }, []);

  const openEditGroup = useCallback((sectionId: number, group: OperationGroup) => {
    setGroupDialogSectionId(sectionId);
    setGroupDialogMode("edit");
    setGroupDialogGroupCode(group.group_code || "");
    setGroupDialogInitial({
      group_code: group.group_code || "",
      group_name: group.group_name || "",
      sort_order: group.sort_order,
    });
    setGroupDialogOpen(true);
  }, []);

  const handleSaveGroup = useCallback(async (values: Record<string, unknown>) => {
    if (groupDialogMode === "add") {
      try {
        const payload = {
          group_code: String(values.group_code || ""),
          group_name: String(values.group_name || ""),
          sort_order: Number(values.sort_order) || 0,
        };
        const created = await SectionsAPI.createOperationGroup(groupDialogSectionId, payload);
        setOpGroups((prev) => [...prev, created]);
        setOpsCountById((prev) => ({ ...prev, [groupDialogSectionId]: (prev[groupDialogSectionId] ?? 0) + created.operations.length }));
        setGroupDialogOpen(false);
        invalidateRelatedCaches();
      } catch (e) {
        toast({ title: "Ошибка создания группы", description: API.getErrorMessage(e), variant: "destructive" });
      }
    } else {
      try {
        const payload: { group_name?: string; sort_order?: number } = {};
        if (values.group_name !== undefined) payload.group_name = String(values.group_name);
        if (values.sort_order !== undefined) payload.sort_order = Number(values.sort_order);
        const updated = await SectionsAPI.updateOperationGroup(groupDialogSectionId, groupDialogGroupCode, payload);
        setOpGroups((prev) => prev.map((g) => g.group_code === groupDialogGroupCode ? updated : g));
        setGroupDialogOpen(false);
        invalidateRelatedCaches();
      } catch (e) {
        toast({ title: "Ошибка обновления группы", description: API.getErrorMessage(e), variant: "destructive" });
      }
    }
  }, [groupDialogMode, groupDialogSectionId, groupDialogGroupCode, invalidateRelatedCaches]);

  const confirmedDeleteGroup = useCallback(async () => {
    if (!deleteGroupDialog) return;
    const { sectionId, groupCode } = deleteGroupDialog;
    try {
      const removedCount = opGroups.find((g) => g.group_code === groupCode)?.operations.length ?? 0;
      await SectionsAPI.deleteOperationGroup(sectionId, groupCode);
      setOpGroups((prev) => prev.filter((g) => g.group_code !== groupCode));
      setOpsCountById((prev) => {
        const cur = prev[sectionId] ?? 0;
        return { ...prev, [sectionId]: Math.max(0, cur - removedCount) };
      });
      setDeleteGroupDialog(null);
      invalidateRelatedCaches();
    } catch (e) {
      toast({ title: "Ошибка удаления группы", description: API.getErrorMessage(e), variant: "destructive" });
    }
  }, [deleteGroupDialog, opGroups, invalidateRelatedCaches]);

  const openMoveOp = useCallback((sectionId: number, op: SectionOperationInfo) => {
    setMoveOpDialog({ sectionId, opId: op.id, opName: op.operation_name, currentGroup: op.group_code });
  }, []);

  const confirmedMoveOp = useCallback(async (targetGroupCode: string) => {
    if (!moveOpDialog) return;
    try {
      await SectionsAPI.moveOperation(moveOpDialog.sectionId, {
        operation_id: moveOpDialog.opId,
        new_group_code: targetGroupCode,
      });
      // Update local state
      const targetGroup = opGroups.find((g) => g.group_code === targetGroupCode);
      setOpGroups((prev) => {
        let next = prev.map((g) => {
          const movedOp = g.operations.find((o) => o.id === moveOpDialog.opId);
          if (!movedOp) return g;
          return {
            ...g,
            operations: g.operations.filter((o) => o.id !== moveOpDialog.opId),
          };
        }).filter((g) => g.operations.length > 0 || g.group_code === null);

        // Add to target group
        const targetGroupName = targetGroup?.group_name || null;
        return next.map((g) =>
          g.group_code === targetGroupCode
            ? { ...g, operations: [...g.operations, { ...moveOpDialog as any, group_code: targetGroupCode, group_name: targetGroupName }] }
            : g,
        );
      });
      setMoveOpDialog(null);
      invalidateRelatedCaches();
    } catch (e) {
      toast({ title: "Ошибка перемещения", description: API.getErrorMessage(e), variant: "destructive" });
    }
  }, [moveOpDialog, opGroups, invalidateRelatedCaches]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const { items: sections, total: sectionsTotal } = await apiListSections({
        limit,
        offset,
        search: debouncedSearch || undefined,
        sort_by: "sort_order",
        sort_order: "asc",
      });
      setItems(sections);
      setTotal(sectionsTotal);
      setOpsCountById((prev) => {
        const next = { ...prev };
        sections.forEach((s) => {
          if (s.id !== undefined) {
            next[Number(s.id)] = s.operations_count ?? 0;
          }
        });
        return next;
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, [limit, offset, debouncedSearch]);

  const commitReorder = useCallback(async () => {
    try {
      const ids = items.map((item) => Number(item.id)).filter(Boolean);
      if (ids.length > 0) {
        await SectionsAPI.reorderSections(ids);
        invalidateRelatedCaches();
      }
    } catch (e) {
      toast({ title: "Ошибка сортировки", description: API.getErrorMessage(e), variant: "destructive" });
      await load();
    }
  }, [items, load, invalidateRelatedCaches]);

  const loadSpgs = useCallback(async () => {
    try {
      const list = await SpgAPI.getSpgList();
      setSpgs(list);
    } catch (e) {
      console.error("Failed to load SPGs:", e);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search), 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    void load();
    void loadSpgs();
  }, [load, loadSpgs]);

  const openAddSpg = () => {
    setSpgDialogMode("add");
    setEditingSpg(null);
    setSpgDialogOpen(true);
  };

  const openEditSpg = (item: SpgAPI.SpgOut) => {
    setSpgDialogMode("edit");
    setEditingSpg(item);
    setSpgDialogOpen(true);
  };

  const handleSaveSpg = async (values: Record<string, unknown>) => {
    const icon = (values.icon as string) || null;
    const icon_color = (values.icon_color as string) || null;
    const description = (values.description as string) || null;

    try {
      if (spgDialogMode === "edit" && editingSpg) {
        const payload: SpgAPI.SpgPatchInput = {
          name: (values.name as string)?.trim(),
          description,
          is_active: values.is_active !== false,
          icon,
          icon_color,
        };
        await SpgAPI.patchSpg(editingSpg.id, payload);
        toast({ title: "Сохранено", description: `ГХП "${payload.name}" обновлено`, variant: "success" });
      } else {
        const payload = {
          code: (values.code as string)?.trim(),
          name: (values.name as string)?.trim(),
          icon,
          icon_color,
          description,
          is_active: values.is_active !== false,
          sort_order: 0,
          section_ids: [],
        };
        const response = await fetch("/api/spg", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!response.ok) throw new Error(`Failed to create SPG: ${response.status}`);
        toast({ title: "Создано", description: `Группа ГХП "${payload.name}" успешно создана`, variant: "success" });
      }
      setSpgDialogOpen(false);
      setEditingSpg(null);
      await loadSpgs();
      invalidateRelatedCaches();
    } catch (e) {
      const action = spgDialogMode === "edit" ? "обновления" : "создания";
      toast({ title: `Ошибка ${action} ГХП`, description: API.getErrorMessage(e), variant: "destructive" });
    }
  };

  const confirmDeleteSpg = async () => {
    if (!deleteSpgDialog) return;
    try {
      await SpgAPI.deleteSpg(deleteSpgDialog.id);
      toast({ title: "Удалено", description: `ГХП "${deleteSpgDialog.name}" удалено`, variant: "success" });
      await Promise.all([loadSpgs(), load()]);
      invalidateRelatedCaches();
    } catch (e) {
      toast({ title: "Ошибка удаления ГХП", description: API.getErrorMessage(e), variant: "destructive" });
    } finally {
      setDeleteSpgDialog(null);
    }
  };

  const openAdd = () => {
    setDialogMode("add");
    setEditingItem(null);
    setDialogOpen(true);
  };

  const openEdit = (item: Section) => {
    setDialogMode("edit");
    setEditingItem(item);
    setDialogOpen(true);
  };

  const handleSave = async (values: Record<string, unknown>) => {
    const spgIdVal = (values.spg_id as number | null | undefined) ?? null;
    const payload = {
      code: (values.code as string)?.trim(),
      name: (values.name as string)?.trim(),
      type: values.type as string,
      icon: (values.icon as string) || null,
      icon_color: (values.icon_color as string) || null,
      description: (values.description as string) || null,
      spg_id: spgIdVal,
    };

    try {
      if (dialogMode === "edit" && editingItem?.id) {
        await apiPatchSection(Number(editingItem.id), payload);
        toast({ title: "Сохранено", description: `Участок "${payload.name}" (код: ${payload.code}, ID: ${editingItem.id}) успешно обновлён`, variant: "success" });
      } else {
        await apiCreateSection(payload);
        toast({ title: "Создано", description: `Участок "${payload.name}" (код: ${payload.code}, тип: ${sectionTypeLabels[payload.type] ?? payload.type}) успешно создан`, variant: "success" });
      }
      setDialogOpen(false);
      await load();
      invalidateRelatedCaches();
    } catch (e) {
      const action = dialogMode === "edit" ? `обновления: ${editingItem?.name} (ID: ${editingItem?.id})` : `создания: ${payload.name}`;
      toast({ title: `Ошибка ${action}`, description: API.getErrorMessage(e), variant: "destructive" });
    }
  };

  const handleDelete = async () => {
    if (!editingItem?.id) return;
    try {
      await apiDeleteSection(Number(editingItem.id));
      toast({ title: "Удалено", description: `Участок "${editingItem.name}" (код: ${editingItem.code}, ID: ${editingItem.id}, тип: ${sectionTypeLabels[editingItem.type ?? "production"] ?? editingItem.type}) успешно удалён`, variant: "success" });
      setDialogOpen(false);
      await load();
      invalidateRelatedCaches();
    } catch (e) {
      toast({ title: `Ошибка удаления: ${editingItem.name} (код: ${editingItem.code}, ID: ${editingItem.id})`, description: API.getErrorMessage(e), variant: "destructive" });
    } finally {
      setDeleteDialogOpen(false);
    }
  };

  const dialogFields = React.useMemo(() => {
    return {
      code: SECTION_FIELDS.code,
      name: SECTION_FIELDS.name,
      spg_id: {
        type: "custom" as const,
        label: "Группа хранения и производства (ГХП)",
        required: true,
        render: ({ value, onChange, hasError, inputClasses }: {
          value: unknown
          onChange: (v: unknown) => void
          id: string
          hasError: boolean
          inputClasses: string
        }) => (
          <SpgSelect
            spgs={spgs}
            value={(value as number | null | undefined) ?? null}
            onValueChange={(v) => onChange(v)}
            placeholder="Выберите ГХП"
            emptyLabel="Без ГХП"
            className={cn("h-10 w-full", hasError ? "border-destructive focus-visible:ring-destructive" : inputClasses)}
          />
        ),
      },
      type: SECTION_FIELDS.type,
      icon: SECTION_FIELDS.icon,
      icon_color: SECTION_FIELDS.icon_color,
      description: SECTION_FIELDS.description,
    };
  }, [spgs]);

  const initialValues = dialogMode === "edit"
    ? {
        code: editingItem?.code ?? "",
        name: editingItem?.name ?? "",
        type: editingItem?.type ?? "production",
        icon: editingItem?.icon ?? "",
        icon_color: editingItem?.icon_color ?? "#3B82F6",
        description: editingItem?.description ?? "",
        spg_id: editingItem?.spg_links?.[0]?.id ?? null,
      }
    : { type: "production", spg_id: null };

  const groups = React.useMemo<Group[]>(() => {
    const groupsMap: Record<string | number, Group> = {};

    spgs.forEach((spg) => {
      groupsMap[spg.id] = {
        spgId: spg.id,
        spgName: spg.name,
        spgIcon: spg.icon,
        spgIconColor: spg.icon_color,
        stocks: [],
        productions: [],
      };
    });

    groupsMap["no-spg"] = {
      spgId: "no-spg",
      spgName: "Без ГХП",
      spgIcon: null,
      spgIconColor: null,
      stocks: [],
      productions: [],
    };

    items.forEach((item) => {
      const isStock = ["raw_stock", "wip_stock", "finished_stock", "scrap"].includes(item.type || "");
      
      if (item.spg_links && item.spg_links.length > 0) {
        item.spg_links.forEach((link) => {
          const group = groupsMap[link.id];
          if (group) {
            if (isStock) {
              group.stocks.push(item);
            } else {
              group.productions.push(item);
            }
          } else {
            if (isStock) {
              groupsMap["no-spg"].stocks.push(item);
            } else {
              groupsMap["no-spg"].productions.push(item);
            }
          }
        });
      } else {
        if (isStock) {
          groupsMap["no-spg"].stocks.push(item);
        } else {
          groupsMap["no-spg"].productions.push(item);
        }
      }
    });

    Object.values(groupsMap).forEach((group) => {
      group.stocks.sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0));
      group.productions.sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0));
    });

    const sortedSpgs = [...spgs].sort((a, b) => a.sort_order - b.sort_order);
    const result: Group[] = [];

    sortedSpgs.forEach((spg) => {
      const group = groupsMap[spg.id];
      if (group && (group.stocks.length > 0 || group.productions.length > 0)) {
        result.push(group);
      }
    });

    const noSpgGroup = groupsMap["no-spg"];
    if (noSpgGroup.stocks.length > 0 || noSpgGroup.productions.length > 0) {
      result.push(noSpgGroup);
    }

    return result;
  }, [items, spgs]);

  const jumpToSpg = (spgId: number | "no-spg") => {
    const el = document.getElementById(`spg-block-${spgId}`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth" });
      if (el instanceof HTMLDetailsElement) {
        el.open = true;
      } else {
        const detailsEl = el.querySelector("details");
        if (detailsEl instanceof HTMLDetailsElement) {
          detailsEl.open = true;
        }
      }
    }
  };

  const moveSectionInSubsection = useCallback(async (sectionId: number, direction: "up" | "down", group: Group, isStock: boolean) => {
    const subsection = isStock ? group.stocks : group.productions;
    const index = subsection.findIndex(s => s.id === sectionId);
    if (index === -1) return;
    const targetIndex = direction === "up" ? index - 1 : index + 1;
    if (targetIndex < 0 || targetIndex >= subsection.length) return;

    const currentItem = subsection[index];
    const targetItem = subsection[targetIndex];

    setItems((prev) => {
      const next = [...prev];
      const idxCurrent = next.findIndex(item => item.id === currentItem.id);
      const idxTarget = next.findIndex(item => item.id === targetItem.id);
      if (idxCurrent !== -1 && idxTarget !== -1) {
        const temp = next[idxCurrent];
        next[idxCurrent] = next[idxTarget];
        next[idxTarget] = temp;
      }
      return next;
    });

    setTimeout(() => {
      void commitReorder();
    }, 0);
  }, [commitReorder]);

  const renderSectionTable = (sectionList: Section[], group: Group, isStock: boolean) => {
    if (sectionList.length === 0) {
      return null;
    }

    return (
      <div className="overflow-x-auto mb-2 border rounded-lg">
        <Table className="w-full table-auto">
          <thead>
            <tr className="bg-muted/30 border-b">
              <th className="py-1.5 px-2 text-left text-xs font-semibold whitespace-nowrap" style={{ width: "35px", minWidth: "35px" }}>⇅</th>
              <th className="py-1.5 px-2 text-left text-xs font-semibold whitespace-nowrap" style={{ width: "45px", minWidth: "45px" }}>Иконка</th>
              <th className="py-1.5 px-2 text-left text-xs font-semibold whitespace-nowrap" style={{ minWidth: "144px", maxWidth: "280px", width: "30%" }}>Название</th>
              <th className="py-1.5 px-2 text-left text-xs font-semibold whitespace-nowrap" style={{ width: "72px", minWidth: "72px" }}>Код</th>
              <th className="py-1.5 px-2 text-left text-xs font-semibold whitespace-nowrap" style={{ minWidth: "112px", maxWidth: "240px", width: "25%" }}>ГХП</th>
              <th className="py-1.5 px-2 text-left text-xs font-semibold whitespace-nowrap" style={{ width: "104px", minWidth: "104px" }}>Тип</th>
              <th className="py-1.5 px-2 text-left text-xs font-semibold whitespace-nowrap" style={{ minWidth: "96px", maxWidth: "280px", width: "25%" }}>Описание</th>
              {!isStock && (
                <th className="py-1.5 px-2 text-center text-xs font-semibold whitespace-nowrap" style={{ width: "96px", minWidth: "96px" }}>Операции</th>
              )}
            </tr>
          </thead>
          <tbody>
            {sectionList.map((item, idx) => (
              <React.Fragment key={String(item.id ?? `${item.code}-${idx}`)}>
                <tr
                  className="transition-colors border-b hover:bg-muted/20"
                  style={item.icon_color ? { backgroundColor: item.icon_color + "18" } : undefined}
                >
                  <td className="py-1.5 px-2 text-xs">
                    <div className="flex items-center gap-0.5">
                      {!isReadOnly && (
                        <>
                          <button
                            type="button"
                            className="p-0.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:cursor-default"
                            disabled={idx === 0}
                            onClick={(e) => { e.stopPropagation(); moveSectionInSubsection(Number(item.id), "up", group, isStock); }}
                            title="Переместить вверх"
                          >
                            <ArrowUp className="h-3.5 w-3.5" />
                          </button>
                          <button
                            type="button"
                            className="p-0.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:cursor-default"
                            disabled={idx === sectionList.length - 1}
                            onClick={(e) => { e.stopPropagation(); moveSectionInSubsection(Number(item.id), "down", group, isStock); }}
                            title="Переместить вниз"
                          >
                            <ArrowDown className="h-3.5 w-3.5" />
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                  <td className="py-1.5 px-2 text-xs cursor-pointer" onClick={() => openEdit(item)}>
                    {item.icon ? (
                      <span style={{ color: item.icon_color || undefined }}>
                        {renderIcon(item.icon, "h-5 w-5")}
                      </span>
                    ) : (
                      <span className="text-muted-foreground text-xs">—</span>
                    )}
                  </td>
                  <td className="py-1.5 px-2 text-xs whitespace-nowrap cursor-pointer" style={{ minWidth: "144px", maxWidth: "280px", width: "30%" }} onClick={() => openEdit(item)}>{item.name}</td>
                  <td className="py-1.5 px-2 text-xs whitespace-nowrap cursor-pointer" style={{ width: "72px", minWidth: "72px" }} onClick={() => openEdit(item)}>{item.code}</td>
                  <td className="py-1.5 px-2 text-xs truncate cursor-pointer" style={{ minWidth: "112px", maxWidth: "240px", width: "25%" }} title={item.spg_links?.map(g => g.name).join(", ") || "—"} onClick={() => openEdit(item)}>
                    {item.spg_links?.map(g => g.name).join(", ") || "—"}
                  </td>
                  <td className="py-1.5 px-2 text-xs truncate cursor-pointer" style={{ width: "104px", minWidth: "104px" }} title={sectionTypeLabels[item.type ?? "production"] ?? item.type ?? "-"} onClick={() => openEdit(item)}>{sectionTypeLabels[item.type ?? "production"] ?? item.type ?? "-"}</td>
                  <td className="py-1.5 px-2 text-xs truncate cursor-pointer" style={{ minWidth: "96px", maxWidth: "280px", width: "25%" }} title={item.description ?? "-"} onClick={() => openEdit(item)}>{item.description ?? "-"}</td>
                  {!isStock && (
                    <td className="py-1.5 px-2 text-xs text-center">
                      <button
                        type="button"
                        onClick={() => toggleSectionOps(Number(item.id), item.name)}
                        className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-sm border transition-colors ${
                          expandedSectionId === Number(item.id)
                            ? "bg-primary/10 border-primary/30 text-primary"
                            : "bg-muted/50 border-border text-foreground hover:bg-muted hover:border-primary/30"
                        }`}
                        title={expandedSectionId === Number(item.id) ? "Скрыть операции" : "Показать операции"}
                      >
                        <span className="text-muted-foreground text-[10px]">Опер.</span>
                        <span className="tabular-nums font-medium">{opsCountById[Number(item.id)] ?? "—"}</span>
                        <ChevronRight
                          className={`h-3.5 w-3.5 transition-transform ${expandedSectionId === Number(item.id) ? "rotate-90" : ""}`}
                        />
                      </button>
                    </td>
                  )}
                </tr>
                {expandedSectionId === Number(item.id) && (
                  <tr key={`ops-${item.id}`}>
                    <td colSpan={isStock ? 7 : 8} className="p-0 border-b bg-muted/10">
                      <div className="max-w-2xl">
                        <div className="bg-muted/30 border-l-4 border-blue-400 p-2 m-1 rounded">
                          <div className="flex items-center gap-2 mb-2">
                            <Settings className="h-3.5 w-3.5 text-blue-600" />
                            <span className="font-semibold text-xs">Операции участка &laquo;{expandedSectionName}&raquo;</span>
                            <span className="text-[10px] text-muted-foreground">Отмеченные операции показываются в плане</span>
                          </div>

                          <div className="flex items-center gap-2 mb-2">
                            {!isReadOnly && (
                              <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => openAddGroup(Number(item.id))}>
                                <Plus className="h-3 w-3 mr-1" />
                                Добавить группу
                              </Button>
                            )}
                          </div>

                          {opsLoading ? (
                            <span className="text-[10px] text-muted-foreground">Загрузка...</span>
                          ) : opGroups.length === 0 ? (
                            <span className="text-[10px] text-muted-foreground">Нет групп операций. Создайте первую группу.</span>
                          ) : (
                            <div className="space-y-2">
                              {opGroups.map((groupOp) => (
                                <div key={groupOp.group_code ?? "__none__"} className="border rounded-lg bg-card">
                                  <div className="flex items-center justify-between px-2 py-1.5 border-b bg-muted/20">
                                    <div className="flex items-center gap-2">
                                      <span className="font-semibold text-xs">{groupOp.group_name || "Без группы"}</span>
                                      {groupOp.group_code && (
                                        <span className="font-mono text-[10px] text-muted-foreground">({groupOp.group_code})</span>
                                      )}
                                      <span className="text-[10px] text-muted-foreground">{groupOp.operations.length} опер.</span>
                                    </div>
                                    <div className="flex items-center gap-0.5">
                                      {groupOp.group_code && !isReadOnly && (
                                        <button
                                          type="button"
                                          onClick={() => openEditGroup(Number(item.id), groupOp)}
                                          className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
                                          title="Редактировать группу"
                                        >
                                          <Pencil className="h-3 w-3" />
                                        </button>
                                      )}
                                      {!isReadOnly && (
                                        <Button size="sm" variant="ghost" className="h-6 px-1.5 text-[10px]" onClick={() => openAddOp(Number(item.id), groupOp.group_code)}>
                                          <Plus className="h-3 w-3 mr-0.5" />
                                          Добавить операцию
                                        </Button>
                                      )}
                                      {groupOp.group_code && !isReadOnly && (
                                        <button
                                          type="button"
                                          onClick={() => setDeleteGroupDialog({ sectionId: Number(item.id), groupCode: groupOp.group_code!, groupName: groupOp.group_name || groupOp.group_code! })}
                                          className="p-1 rounded hover:bg-destructive/20 text-muted-foreground hover:text-destructive"
                                          title="Удалить группу"
                                        >
                                          <Trash2 className="h-3 w-3" />
                                        </button>
                                      )}
                                    </div>
                                  </div>

                                  <div className="flex items-center gap-1 flex-wrap p-1.5">
                                    {groupOp.operations.length === 0 ? (
                                      <span className="text-[10px] text-muted-foreground px-2">Нет операций</span>
                                    ) : (
                                      groupOp.operations
                                        .filter((op) => !op.operation_code.startsWith("__"))
                                        .map((op) => (
                                          <div
                                            key={op.id}
                                            className="flex items-center gap-1 px-1.5 h-6 rounded border bg-card hover:bg-accent/50 transition-colors text-xs group/op cursor-pointer"
                                            onClick={() => openEditOp(Number(item.id), op)}
                                          >
                                            <input
                                              type="checkbox"
                                              checked={op.is_significant}
                                              onChange={() => toggleOpSignificant(Number(item.id), op.id, op.is_significant)}
                                              disabled={isReadOnly}
                                              className="rounded border-gray-300 cursor-pointer h-3 w-3"
                                            />
                                            {op.icon ? (
                                              <span style={{ color: op.icon_color || undefined }} className="shrink-0">
                                                {renderIcon(op.icon, "h-3 w-3")}
                                              </span>
                                            ) : op.icon_color ? (
                                              <span className="inline-block size-3 shrink-0 rounded-full bg-current" style={{ color: op.icon_color }} />
                                            ) : null}
                                            <span className="font-mono text-[10px] text-muted-foreground">{op.operation_code}</span>
                                            <span className="text-[10px]">{op.operation_name}</span>
                                            {op.is_significant && <Badge variant="secondary" className="text-[10px] bg-green-100 text-green-700 shrink-0">★</Badge>}
                                            {!isReadOnly && (
                                              <div className="flex items-center gap-0.5 opacity-0 group-hover/op:opacity-100 transition-opacity">
                                                {opGroups.length > 1 && (
                                                  <button
                                                    type="button"
                                                    onClick={(e) => { e.stopPropagation(); openMoveOp(Number(item.id), op); }}
                                                    className="p-0.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
                                                    title="Переместить в другую группу"
                                                  >
                                                    <Move className="h-2.5 w-2.5" />
                                                  </button>
                                                )}
                                                <button
                                                  type="button"
                                                  onClick={(e) => { e.stopPropagation(); deleteOp(Number(item.id), op.id, op.operation_name); }}
                                                  className="p-0.5 rounded hover:bg-destructive/20 text-muted-foreground hover:text-destructive"
                                                  title="Удалить"
                                                >
                                                  <X className="h-2.5 w-2.5" />
                                                </button>
                                              </div>
                                            )}
                                          </div>
                                        ))
                                    )}
                                  </div>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </Table>
      </div>
    );
  };

  const getSpgCounters = (spgId: number | "no-spg") => {
    const group = groups.find(g => g.spgId === spgId);
    return {
      stocks: group?.stocks.length ?? 0,
      productions: group?.productions.length ?? 0,
    };
  };

  const visibleSpgCount = useMemo(
    () => spgs.filter((s) => {
      const c = getSpgCounters(s.id);
      return c.stocks > 0 || c.productions > 0;
    }).length,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [spgs, groups]
  );

  const noSpgVisible = useMemo(() => {
    const c = getSpgCounters("no-spg");
    return c.stocks > 0 || c.productions > 0;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groups]);

  const navBadgeCount = visibleSpgCount + (noSpgVisible ? 1 : 0);

  return (
    <section style={{ display: "grid", gap: 12 }}>
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">ГХП — Группа хранения и производства</h2>
        <div className="flex items-center gap-2">
          {!isReadOnly && (
            <>
              <Button size="sm" variant="outline" onClick={openAddSpg}>
                <Plus className="h-4 w-4 mr-1" />
                Добавить ГХП
              </Button>
              <Button size="sm" onClick={openAdd}>
                <Plus className="h-4 w-4 mr-1" />
                Добавить участок
              </Button>
            </>
          )}
        </div>
      </div>

      <EntityDialog
        fields={dialogFields}
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        mode={dialogMode}
        initialValues={initialValues}
        onSave={handleSave}
        onDelete={dialogMode === "edit" && !isReadOnly ? () => setDeleteDialogOpen(true) : undefined}
        readOnly={isReadOnly}
        addTitle="Новый участок"
        editTitle="Редактировать участок"
        addDescription="Заполните информацию об участке"
        editDescription="Измените параметры участка"
        addLabel="Создать"
        saveLabel="Сохранить"
      />

      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent className="max-w-sm">
          <AlertDialogHeader>
            <AlertDialogTitle>Удалить {editingItem?.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              Это действие нельзя отменить. Участок и все его операции будут удалены навсегда.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter className="flex-col-reverse sm:flex-row gap-2">
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">
              Удалить
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={!!deleteOpDialog} onOpenChange={(open) => !open && setDeleteOpDialog(null)}>
        <AlertDialogContent className="max-w-sm">
          <AlertDialogHeader>
            <AlertDialogTitle>Удалить операцию &laquo;{deleteOpDialog?.opName}&raquo;?</AlertDialogTitle>
            <AlertDialogDescription>
              Это действие нельзя отменить. Операция будет удалена навсегда.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter className="flex-col-reverse sm:flex-row gap-2">
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction onClick={confirmedDeleteOp} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">
              Удалить
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <div className="flex flex-col sm:flex-row gap-2 items-start sm:items-center justify-between">
        <div className="relative w-72">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Поиск по коду, названию, описанию, ГХП"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
        <TablePaginationFooter
          page={page}
          totalPages={totalPages}
          total={total}
          shownCount={items.length}
          limit={limit}
          onPageChange={setPage}
          onLimitChange={setLimit}
          rangeLabel={getRangeLabel(items.length, total, { onPage: true })}
        />
      </div>

      {error ? <div role="alert">{error}</div> : null}
      {loading ? <div>Загрузка...</div> : null}

      <div className="grid gap-3 items-start" style={{ gridTemplateColumns: "minmax(0, 7fr) minmax(0, 3fr)" }}>
        <div className="space-y-4 pr-5">
          {groups.map((group) => {
            const totalStocks = group.stocks.length;
            const totalProds = group.productions.length;
            
            return (
              <div 
                key={group.spgId} 
                id={`spg-block-${group.spgId}`} 
                className="scroll-mt-4"
              >
                <details
                  open
                  className="border rounded-xl bg-card overflow-hidden shadow-sm transition-all"
                >
                  <summary className="cursor-pointer select-none px-3 py-2 flex items-center gap-2 bg-muted/30 hover:bg-muted/50 border-b transition-colors font-medium">
                    {group.spgIcon ? (
                      <span style={{ color: group.spgIconColor || undefined }}>
                        {renderIcon(group.spgIcon, "h-4 w-4")}
                      </span>
                    ) : group.spgIconColor ? (
                      <span className="inline-block size-4 rounded-full bg-current" style={{ color: group.spgIconColor }} />
                    ) : (
                      <Layers className="h-4 w-4 text-muted-foreground" />
                    )}
                    <span className="text-sm font-semibold flex-1 text-foreground">{group.spgName}</span>
                    <div className="flex items-center gap-1.5">
                      <Badge variant="secondary" className="text-[10px] bg-blue-50 text-blue-700 dark:bg-blue-950/30 border border-blue-200">
                        Склады: {totalStocks}
                      </Badge>
                      <Badge variant="secondary" className="text-[10px] bg-indigo-50 text-indigo-700 dark:bg-indigo-950/30 border border-indigo-200">
                        Производство: {totalProds}
                      </Badge>
                    </div>
                  </summary>
                  <div className="p-2 space-y-2 bg-card">
                    {group.productions.length > 0 && (
                      <div>
                        <h4 className="text-xs font-medium text-muted-foreground mb-1.5 flex items-center gap-2">
                          <Factory className="h-3.5 w-3.5" />
                          <span>Производственные участки</span>
                          <Badge variant="outline" className="text-[10px] py-0 px-1.5">{totalProds}</Badge>
                        </h4>
                        {renderSectionTable(group.productions, group, false)}
                      </div>
                    )}

                    {group.stocks.length > 0 && (
                      <div>
                        <h4 className="text-xs font-medium text-muted-foreground mb-1.5 flex items-center gap-2">
                          <Warehouse className="h-3.5 w-3.5" />
                          <span>Склады</span>
                          <Badge variant="outline" className="text-[10px] py-0 px-1.5">{totalStocks}</Badge>
                        </h4>
                        {renderSectionTable(group.stocks, group, true)}
                      </div>
                    )}
                  </div>
                </details>
              </div>
            );
          })}
        </div>

        <details open className="border rounded-lg bg-card overflow-hidden self-start sticky top-2 shadow-sm">
          <summary className="cursor-pointer select-none px-3 py-2 flex items-center gap-2 text-sm font-medium hover:bg-accent/40 transition-colors border-b">
            <Layers className="h-4 w-4 text-muted-foreground" />
            <span className="flex-1">Навигация по ГХП</span>
            <Badge variant="secondary" className="text-xs">{navBadgeCount}</Badge>
          </summary>
          <div className="max-h-[400px] overflow-y-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-muted/20 border-b text-xs text-muted-foreground">
                  <th className="py-1 px-2 text-left font-medium w-8"></th>
                  <th className="py-1 px-2 text-left font-medium">Название</th>
                  <th className="py-1 px-2 text-right font-medium w-24">Участки</th>
                  <th className="py-1 px-2 text-center font-medium w-10"></th>
                </tr>
              </thead>
              <tbody>
                {spgs.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="py-3 px-2 text-xs text-center text-muted-foreground">
                      Нет ГХП
                    </td>
                  </tr>
                ) : (
                  spgs.map((spg) => {
                    const counters = getSpgCounters(spg.id);
                    if (counters.stocks === 0 && counters.productions === 0) return null;
                    return (
                      <tr
                        key={spg.id}
                        className="border-b transition-colors hover:bg-accent/40 cursor-pointer"
                        onClick={() => jumpToSpg(spg.id)}
                        style={spg.icon_color ? { backgroundColor: spg.icon_color + "07" } : undefined}
                      >
                        <td className="py-1.5 px-2">
                          {spg.icon ? (
                            <span style={{ color: spg.icon_color || undefined }}>
                              {renderIcon(spg.icon, "h-4 w-4")}
                            </span>
                          ) : spg.icon_color ? (
                            <span className="inline-block size-3.5 rounded-full bg-current" style={{ color: spg.icon_color }} />
                          ) : (
                            <Layers className="h-4 w-4 text-muted-foreground" />
                          )}
                        </td>
                        <td className="py-1.5 px-2 text-sm truncate font-medium" title={spg.name}>{spg.name}</td>
                        <td className="py-1.5 px-2 text-[10px] text-muted-foreground text-right tabular-nums whitespace-nowrap">
                          С:{counters.stocks} · П:{counters.productions}
                        </td>
                        <td className="py-1.5 px-2 text-center" onClick={(e) => e.stopPropagation()}>
                          {!isReadOnly && (
                            <button
                              type="button"
                              onClick={() => openEditSpg(spg)}
                              className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
                              title="Редактировать ГХП"
                            >
                              <Pencil className="h-3 w-3" />
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })
                )}
                {(() => {
                  const noSpgCounters = getSpgCounters("no-spg");
                  if (noSpgCounters.stocks > 0 || noSpgCounters.productions > 0) {
                    return (
                      <tr
                        className="border-b transition-colors hover:bg-accent/40 cursor-pointer"
                        onClick={() => jumpToSpg("no-spg")}
                      >
                        <td className="py-1.5 px-2">
                          <Layers className="h-4 w-4 text-muted-foreground" />
                        </td>
                        <td className="py-1.5 px-2 text-sm truncate font-medium text-muted-foreground">Без ГХП</td>
                        <td className="py-1.5 px-2 text-[10px] text-muted-foreground text-right tabular-nums whitespace-nowrap">
                          С:{noSpgCounters.stocks} · П:{noSpgCounters.productions}
                        </td>
                        <td className="py-1.5 px-2 text-center"></td>
                      </tr>
                    );
                  }
                  return null;
                })()}
              </tbody>
            </table>
          </div>
        </details>
      </div>
    <EntityDialog
        fields={OP_FIELDS}
        open={opDialogOpen}
        onOpenChange={setOpDialogOpen}
        mode={opDialogMode}
        initialValues={opDialogInitial}
        onSave={handleSaveOp}
        onDelete={opDialogMode === "edit" ? () => { deleteOp(opDialogSectionId, opDialogOpId, String(opDialogInitial.operation_name || "")); } : undefined}
        addTitle="Новая операция"
        editTitle="Редактировать операцию"
        addDescription="Заполните информацию об операции"
        editDescription="Измените параметры операции"
        addLabel="Создать"
        saveLabel="Сохранить"
      />

      {/* Group create/edit dialog */}
      <EntityDialog
        fields={GROUP_FIELDS}
        open={groupDialogOpen}
        onOpenChange={setGroupDialogOpen}
        mode={groupDialogMode}
        initialValues={groupDialogInitial}
        onSave={handleSaveGroup}
        readOnly={isReadOnly}
        addTitle="Новая группа операций"
        editTitle="Редактировать группу"
        addDescription="Заполните информацию о группе"
        editDescription="Измените параметры группы"
        addLabel="Создать"
        saveLabel="Сохранить"
        dialogWidth="sm:max-w-[700px]"
      />

      {/* Delete group confirmation */}
      <AlertDialog open={!!deleteGroupDialog} onOpenChange={(open) => !open && setDeleteGroupDialog(null)}>
        <AlertDialogContent className="max-w-sm">
          <AlertDialogHeader>
            <AlertDialogTitle>Удалить группу &laquo;{deleteGroupDialog?.groupName}&raquo;?</AlertDialogTitle>
            <AlertDialogDescription>
              Это действие нельзя отменить. Все операции группы будут удалены.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter className="flex-col-reverse sm:flex-row gap-2">
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction onClick={confirmedDeleteGroup} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">
              Удалить
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Move operation dialog */}
      <AlertDialog open={!!moveOpDialog} onOpenChange={(open) => !open && setMoveOpDialog(null)}>
        <AlertDialogContent className="max-w-sm">
          <AlertDialogHeader>
            <AlertDialogTitle>Переместить &laquo;{moveOpDialog?.opName}&raquo;</AlertDialogTitle>
            <AlertDialogDescription>
              Выберите целевую группу для операции &laquo;{moveOpDialog?.opName}&raquo;
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-2 py-2">
            {opGroups
              .filter((g) => g.group_code !== moveOpDialog?.currentGroup && g.group_code !== null)
              .map((g) => (
                <button
                  key={g.group_code!}
                  type="button"
                  className="w-full text-left px-3 py-2 rounded-md border bg-card hover:bg-accent transition-colors text-sm"
                  onClick={() => confirmedMoveOp(g.group_code!)}
                >
                  <span className="font-semibold">{g.group_name}</span>
                  <span className="font-mono text-xs text-muted-foreground ml-2">({g.group_code})</span>
                </button>
              ))}
          </div>
          <AlertDialogFooter className="flex-col-reverse sm:flex-row gap-2">
            <AlertDialogCancel>Отмена</AlertDialogCancel>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <EntityDialog
        fields={SPG_FIELDS}
        open={spgDialogOpen}
        onOpenChange={(open) => {
          setSpgDialogOpen(open);
          if (!open) setEditingSpg(null);
        }}
        mode={spgDialogMode}
        initialValues={spgDialogMode === "edit" && editingSpg ? {
          code: editingSpg.code,
          name: editingSpg.name,
          is_active: editingSpg.is_active,
          icon: editingSpg.icon ?? "",
          icon_color: editingSpg.icon_color ?? "#3B82F6",
          description: editingSpg.description ?? "",
        } : { is_active: true }}
        onSave={handleSaveSpg}
        onDelete={spgDialogMode === "edit" && editingSpg && !isReadOnly ? () => setDeleteSpgDialog({ id: editingSpg.id, name: editingSpg.name }) : undefined}
        readOnly={isReadOnly}
        addTitle="Новая группа хранения и производства (ГХП)"
        editTitle="Редактировать ГХП"
        addDescription="Заполните информацию о ГХП"
        editDescription="Измените параметры ГХП"
        addLabel="Создать"
        saveLabel="Сохранить"
      />

      <AlertDialog open={!!deleteSpgDialog} onOpenChange={(open) => !open && setDeleteSpgDialog(null)}>
        <AlertDialogContent className="max-w-sm">
          <AlertDialogHeader>
            <AlertDialogTitle>Удалить ГХП &laquo;{deleteSpgDialog?.name}&raquo;?</AlertDialogTitle>
            <AlertDialogDescription>
              Это действие нельзя отменить. Группа хранения и производства и все её привязки к участкам будут удалены.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter className="flex-col-reverse sm:flex-row gap-2">
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction onClick={confirmDeleteSpg} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">
              Удалить
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}
