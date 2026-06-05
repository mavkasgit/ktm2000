import React, { useCallback, useEffect, useState } from "react";
import { Plus, ArrowUp, ArrowDown, GripVertical, Settings, X, Pencil, Trash2, Move, Layers, ChevronRight } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import * as API from "shared/api";
import * as SectionsAPI from "shared/api/sections";
import * as ShopfloorAPI from "shared/api/shopfloor";
import * as SpgAPI from "shared/api/spg";
import * as UI from "shared/ui";
import { Button } from "@/shared/ui/Button";
import { Badge } from "@/shared/ui/Badge";
import { EntityDialog, renderIcon } from "@/shared/ui/EntityDialog";
import { SpgSelect } from "@/shared/ui/SpgSelect";
import { cn } from "@/shared/utils/cn";
import { Popover, PopoverTrigger, PopoverContent } from "@/shared/ui/Popover";
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogCancel, AlertDialogAction } from "@/shared/ui/AlertDialog";
import { toast } from "@/shared/ui/use-toast";
import type { EntityDialogField } from "@/shared/ui/EntityDialog";
import type { OperationGroup, SectionOperationInfo } from "shared/api/sections";

type Section = {
  id?: string | number;
  code: string;
  name: string;
  description?: string | null;
  kind?: string;
  icon?: string | null;
  icon_color?: string | null;
  sort_order?: number;
  spg_links?: { id: number; code: string; name: string }[];
  operations_count?: number;
};

const KIND_LABELS: Record<string, string> = {
  production: "Производство",
  raw_stock: "Склад сырья",
  wip_stock: "Склад полуфабриката",
  finished_stock: "Склад готовой продукции",
};

const KIND_OPTIONS = [
  { value: "production", label: "Производство" },
  { value: "raw_stock", label: "Склад сырья" },
  { value: "wip_stock", label: "Склад полуфабриката" },
  { value: "finished_stock", label: "Склад готовой продукции" },
];

const ui = UI as Record<string, React.ComponentType<any>>;
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
  kind: { type: "select", label: "Тип", required: true, options: KIND_OPTIONS },
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

async function apiListSections(): Promise<Section[]> {
  const api = API as Record<string, any>;
  if (typeof api.listSections === "function") {
    return api.listSections();
  }
  const response = await fetch("/api/sections");
  if (!response.ok) throw new Error(`Failed to load sections: ${response.status}`);
  return response.json();
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
  const queryClient = useQueryClient();
  const [items, setItems] = useState<Section[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogMode, setDialogMode] = useState<"add" | "edit">("add");
  const [editingItem, setEditingItem] = useState<Section | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [draggedIndex, setDraggedIndex] = useState<number | null>(null);
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
      await queryClient.invalidateQueries({ queryKey: ["shopfloor"] });
    } catch (e) {
      toast({ title: "Ошибка обновления", description: API.getErrorMessage(e), variant: "destructive" });
    }
  }, [queryClient]);

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
        await queryClient.invalidateQueries({ queryKey: ["shopfloor"] });
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
        await queryClient.invalidateQueries({ queryKey: ["shopfloor"] });
        setOpDialogOpen(false);
      } catch (e) {
        toast({ title: "Ошибка обновления", description: API.getErrorMessage(e), variant: "destructive" });
      }
    }
  }, [opDialogMode, opDialogSectionId, opDialogOpId, opDialogGroupCode, opGroups, queryClient]);

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
      await queryClient.invalidateQueries({ queryKey: ["shopfloor"] });
    } catch (e) {
      toast({ title: "Ошибка удаления", description: API.getErrorMessage(e), variant: "destructive" });
    } finally {
      setDeleteOpDialog(null);
    }
  }, [deleteOpDialog, queryClient]);

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
      } catch (e) {
        toast({ title: "Ошибка обновления группы", description: API.getErrorMessage(e), variant: "destructive" });
      }
    }
  }, [groupDialogMode, groupDialogSectionId, groupDialogGroupCode]);

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
    } catch (e) {
      toast({ title: "Ошибка удаления группы", description: API.getErrorMessage(e), variant: "destructive" });
    }
  }, [deleteGroupDialog, opGroups]);

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
    } catch (e) {
      toast({ title: "Ошибка перемещения", description: API.getErrorMessage(e), variant: "destructive" });
    }
  }, [moveOpDialog, opGroups]);

  const moveItem = useCallback((fromIndex: number, toIndex: number) => {
    setItems((prev) => {
      if (toIndex < 0 || toIndex >= prev.length) return prev;
      const next = [...prev];
      const [moved] = next.splice(fromIndex, 1);
      next.splice(toIndex, 0, moved);
      return next;
    });
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const sections = await apiListSections();
      setItems(sections);
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
  }, []);

  const commitReorder = useCallback(async () => {
    try {
      const ids = items.map((item) => Number(item.id)).filter(Boolean);
      if (ids.length > 0) {
        await SectionsAPI.reorderSections(ids);
        await queryClient.invalidateQueries({ queryKey: ["sections"] });
        await queryClient.invalidateQueries({ queryKey: ["shopfloor-sections-summary"] });
      }
    } catch (e) {
      toast({ title: "Ошибка сортировки", description: API.getErrorMessage(e), variant: "destructive" });
      await load();
    }
  }, [items, load, queryClient]);

  const moveItemUp = useCallback(async (index: number) => {
    moveItem(index, index - 1);
    setTimeout(() => commitReorder(), 0);
  }, [moveItem, commitReorder]);

  const moveItemDown = useCallback(async (index: number) => {
    moveItem(index, index + 1);
    setTimeout(() => commitReorder(), 0);
  }, [moveItem, commitReorder]);

  const handleDragStart = useCallback((index: number) => {
    setDraggedIndex(index);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent, index: number) => {
    e.preventDefault();
    if (draggedIndex === null || draggedIndex === index) return;
    moveItem(draggedIndex, index);
    setDraggedIndex(index);
  }, [draggedIndex, moveItem]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDraggedIndex(null);
    void commitReorder();
  }, [commitReorder]);

  const handleDragEnd = useCallback(() => {
    setDraggedIndex(null);
  }, []);

  const loadSpgs = useCallback(async () => {
    try {
      const list = await SpgAPI.getSpgList();
      setSpgs(list);
    } catch (e) {
      console.error("Failed to load SPGs:", e);
    }
  }, []);

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
      kind: values.kind as string,
      icon: (values.icon as string) || null,
      icon_color: (values.icon_color as string) || null,
      description: (values.description as string) || null,
      spg_ids: spgIdVal ? [spgIdVal] : [],
    };

    try {
      if (dialogMode === "edit" && editingItem?.id) {
        await apiPatchSection(Number(editingItem.id), payload);
        toast({ title: "Сохранено", description: `Участок "${payload.name}" (код: ${payload.code}, ID: ${editingItem.id}) успешно обновлён`, variant: "success" });
      } else {
        await apiCreateSection(payload);
        toast({ title: "Создано", description: `Участок "${payload.name}" (код: ${payload.code}, тип: ${KIND_LABELS[payload.kind] ?? payload.kind}) успешно создан`, variant: "success" });
      }
      setDialogOpen(false);
      await load();
    } catch (e) {
      const action = dialogMode === "edit" ? `обновления: ${editingItem?.name} (ID: ${editingItem?.id})` : `создания: ${payload.name}`;
      toast({ title: `Ошибка ${action}`, description: API.getErrorMessage(e), variant: "destructive" });
    }
  };

  const handleDelete = async () => {
    if (!editingItem?.id) return;
    try {
      await apiDeleteSection(Number(editingItem.id));
      toast({ title: "Удалено", description: `Участок "${editingItem.name}" (код: ${editingItem.code}, ID: ${editingItem.id}, тип: ${KIND_LABELS[editingItem.kind ?? "production"] ?? editingItem.kind}) успешно удалён`, variant: "success" });
      setDialogOpen(false);
      await load();
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
        required: false,
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
      kind: SECTION_FIELDS.kind,
      icon: SECTION_FIELDS.icon,
      icon_color: SECTION_FIELDS.icon_color,
      description: SECTION_FIELDS.description,
    };
  }, [spgs]);

  const initialValues = dialogMode === "edit"
    ? {
        code: editingItem?.code ?? "",
        name: editingItem?.name ?? "",
        kind: editingItem?.kind ?? "production",
        icon: editingItem?.icon ?? "",
        icon_color: editingItem?.icon_color ?? "#3B82F6",
        description: editingItem?.description ?? "",
        spg_id: editingItem?.spg_links?.[0]?.id ?? null,
      }
    : { kind: "production", spg_id: null };

  return (
    <section style={{ display: "grid", gap: 12 }}>
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Участки</h2>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" onClick={openAddSpg}>
            <Plus className="h-4 w-4 mr-1" />
            Добавить ГХП
          </Button>
          <Button size="sm" onClick={openAdd}>
            <Plus className="h-4 w-4 mr-1" />
            Добавить участок
          </Button>
        </div>
      </div>

      <EntityDialog
        fields={dialogFields}
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        mode={dialogMode}
        initialValues={initialValues}
        onSave={handleSave}
        onDelete={dialogMode === "edit" ? () => setDeleteDialogOpen(true) : undefined}
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

      {error ? <div role="alert">{error}</div> : null}
      {loading ? <div>Загрузка...</div> : null}

      <div className="grid gap-3 items-start" style={{ gridTemplateColumns: "minmax(0, 1fr) 260px" }}>
        <div className="overflow-x-auto pr-5">
          <Table className="w-full table-auto">
            <thead>
              <tr>
                <th className="py-3 px-2 text-left text-sm font-medium whitespace-nowrap" style={{ width: "44px", minWidth: "44px" }}>⇅</th>
                <th className="py-3 px-3 text-left text-sm font-medium whitespace-nowrap" style={{ width: "56px", minWidth: "56px" }}>Иконка</th>
                <th className="py-3 px-3 text-left text-sm font-medium whitespace-nowrap" style={{ minWidth: "180px", maxWidth: "350px", width: "30%" }}>Название</th>
                <th className="py-3 px-3 text-left text-sm font-medium whitespace-nowrap" style={{ width: "90px", minWidth: "90px" }}>Код</th>
                <th className="py-3 px-3 text-left text-sm font-medium whitespace-nowrap" style={{ minWidth: "140px", maxWidth: "300px", width: "25%" }}>ГХП</th>
                <th className="py-3 px-3 text-left text-sm font-medium whitespace-nowrap" style={{ width: "130px", minWidth: "130px" }}>Тип</th>
                <th className="py-3 px-3 text-left text-sm font-medium whitespace-nowrap" style={{ minWidth: "120px", maxWidth: "350px", width: "25%" }}>Описание</th>
                <th className="py-3 px-3 text-center text-sm font-medium whitespace-nowrap" style={{ width: "120px", minWidth: "120px" }}>Операции</th>
              </tr>
            </thead>
          <tbody>
            {items.map((item, i) => (
              <React.Fragment key={String(item.id ?? `${item.code}-${i}`)}>
              <tr
                className="transition-colors"
                draggable
                onDragStart={(e) => {
                  (e.currentTarget as HTMLTableRowElement).style.opacity = "0.4";
                  handleDragStart(i);
                }}
                onDragOver={(e) => handleDragOver(e, i)}
                onDrop={(e) => {
                  (e.currentTarget as HTMLTableRowElement).style.opacity = "1";
                  handleDrop(e);
                }}
                onDragEnd={(e) => {
                  (e.currentTarget as HTMLTableRowElement).style.opacity = "1";
                  handleDragEnd();
                }}
                style={item.icon_color ? { backgroundColor: item.icon_color + "18" } : undefined}
                onMouseEnter={(e) => {
                  if (item.icon_color) (e.currentTarget as HTMLTableRowElement).style.backgroundColor = item.icon_color + "40"
                }}
                onMouseLeave={(e) => {
                  if (item.icon_color) (e.currentTarget as HTMLTableRowElement).style.backgroundColor = item.icon_color + "18"
                }}
              >
                <td className="py-3 px-2 text-sm">
                  <div className="flex items-center gap-0.5">
                    <span className="cursor-grab active:cursor-grabbing text-muted-foreground hover:text-foreground">
                      <GripVertical className="h-4 w-4" />
                    </span>
                    <button
                      type="button"
                      className="p-0.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:cursor-default"
                      disabled={i === 0}
                      onClick={(e) => { e.stopPropagation(); moveItemUp(i); }}
                      title="Переместить вверх"
                    >
                      <ArrowUp className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      className="p-0.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:cursor-default"
                      disabled={i === items.length - 1}
                      onClick={(e) => { e.stopPropagation(); moveItemDown(i); }}
                      title="Переместить вниз"
                    >
                      <ArrowDown className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </td>
                <td className="py-3 px-4 text-sm cursor-pointer" onClick={() => openEdit(item)}>
                  {item.icon ? (
                    <span style={{ color: item.icon_color || undefined }}>
                      {renderIcon(item.icon, "h-6 w-6")}
                    </span>
                  ) : (
                    <span className="text-muted-foreground text-sm">—</span>
                  )}
                </td>
                <td className="py-3 px-4 text-sm whitespace-nowrap cursor-pointer" style={{ minWidth: "180px", maxWidth: "350px", width: "30%" }} onClick={() => openEdit(item)}>{item.name}</td>
                <td className="py-3 px-4 text-sm whitespace-nowrap cursor-pointer" style={{ width: "90px", minWidth: "90px" }} onClick={() => openEdit(item)}>{item.code}</td>
                <td className="py-3 px-4 text-sm truncate cursor-pointer" style={{ minWidth: "140px", maxWidth: "300px", width: "25%" }} title={item.spg_links?.map(g => g.name).join(", ") || "—"} onClick={() => openEdit(item)}>
                  {item.spg_links?.map(g => g.name).join(", ") || "—"}
                </td>
                <td className="py-3 px-4 text-sm truncate cursor-pointer" style={{ width: "130px", minWidth: "130px" }} title={KIND_LABELS[item.kind ?? "production"] ?? item.kind ?? "-"} onClick={() => openEdit(item)}>{KIND_LABELS[item.kind ?? "production"] ?? item.kind ?? "-"}</td>
                <td className="py-3 px-4 text-sm truncate cursor-pointer" style={{ minWidth: "120px", maxWidth: "350px", width: "25%" }} title={item.description ?? "-"} onClick={() => openEdit(item)}>{item.description ?? "-"}</td>
                <td className="py-3 px-2 text-sm text-center">
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
                    <span className="text-muted-foreground text-xs">Опер.</span>
                    <span className="tabular-nums font-medium">{opsCountById[Number(item.id)] ?? "—"}</span>
                    <ChevronRight
                      className={`h-3.5 w-3.5 transition-transform ${expandedSectionId === Number(item.id) ? "rotate-90" : ""}`}
                    />
                  </button>
                </td>
              </tr>
              {expandedSectionId === Number(item.id) && (
                <tr key={`ops-${item.id}`}>
                  <td colSpan={8} className="p-0">
                    <div className="max-w-2xl">
                    <div className="bg-muted/30 border-l-4 border-blue-400 p-4 m-2 rounded">
                      <div className="flex items-center gap-2 mb-3">
                        <Settings className="h-4 w-4 text-blue-600" />
                        <span className="font-semibold text-sm">Операции участка &laquo;{expandedSectionName}&raquo;</span>
                        <span className="text-xs text-muted-foreground">Отмеченные операции показываются в плане</span>
                      </div>

                      <div className="flex items-center gap-2 mb-3">
                        <Button size="sm" variant="outline" className="h-8" onClick={() => openAddGroup(Number(item.id))}>
                          <Plus className="h-3 w-3 mr-1" />
                          Добавить группу
                        </Button>
                      </div>

                      {opsLoading ? (
                        <span className="text-xs text-muted-foreground">Загрузка...</span>
                      ) : opGroups.length === 0 ? (
                        <span className="text-xs text-muted-foreground">Нет групп операций. Создайте первую группу.</span>
                      ) : (
                        <div className="space-y-3">
                          {opGroups.map((group) => (
                            <div key={group.group_code ?? "__none__"} className="border rounded-lg bg-card">
                              {/* Group header */}
                              <div className="flex items-center justify-between px-3 py-2 border-b bg-muted/20">
                                <div className="flex items-center gap-2">
                                  <span className="font-semibold text-sm">{group.group_name || "Без группы"}</span>
                                  {group.group_code && (
                                    <span className="font-mono text-xs text-muted-foreground">({group.group_code})</span>
                                  )}
                                  <span className="text-xs text-muted-foreground">{group.operations.length} опер.</span>
                                </div>
                                <div className="flex items-center gap-1">
                                  {group.group_code && (
                                    <button
                                      type="button"
                                      onClick={() => openEditGroup(Number(item.id), group)}
                                      className="p-1.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
                                      title="Редактировать группу"
                                    >
                                      <Pencil className="h-3.5 w-3.5" />
                                    </button>
                                  )}
                                  <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" onClick={() => openAddOp(Number(item.id), group.group_code)}>
                                    <Plus className="h-3 w-3 mr-0.5" />
                                    Добавить операцию
                                  </Button>
                                  {group.group_code && (
                                    <button
                                      type="button"
                                      onClick={() => setDeleteGroupDialog({ sectionId: Number(item.id), groupCode: group.group_code!, groupName: group.group_name || group.group_code! })}
                                      className="p-1.5 rounded hover:bg-destructive/20 text-muted-foreground hover:text-destructive"
                                      title="Удалить группу"
                                    >
                                      <Trash2 className="h-3.5 w-3.5" />
                                    </button>
                                  )}
                                </div>
                              </div>

                              {/* Operations in group */}
                              <div className="flex items-center gap-1.5 flex-wrap p-2">
                                {group.operations.length === 0 ? (
                                  <span className="text-xs text-muted-foreground px-2">Нет операций</span>
                                ) : (
                                  group.operations
                                    .filter((op) => !op.operation_code.startsWith("__"))
                                    .map((op) => (
                                      <div
                                        key={op.id}
                                        className="flex items-center gap-1 px-2 h-8 rounded border bg-card hover:bg-accent/50 transition-colors text-sm group/op cursor-pointer"
                                        onClick={() => openEditOp(Number(item.id), op)}
                                      >
                                        <input
                                          type="checkbox"
                                          checked={op.is_significant}
                                          onChange={() => toggleOpSignificant(Number(item.id), op.id, op.is_significant)}
                                          className="rounded border-gray-300 cursor-pointer h-3.5 w-3.5"
                                        />
                                        {op.icon ? (
                                          <span style={{ color: op.icon_color || undefined }} className="shrink-0">
                                            {renderIcon(op.icon, "h-3.5 w-3.5")}
                                          </span>
                                        ) : op.icon_color ? (
                                          <span className="inline-block size-3.5 shrink-0 rounded-full bg-current" style={{ color: op.icon_color }} />
                                        ) : null}
                                        <span className="font-mono text-xs text-muted-foreground">{op.operation_code}</span>
                                        <span className="text-xs">{op.operation_name}</span>
                                        {op.is_significant && <Badge variant="secondary" className="text-xs bg-green-100 text-green-700 shrink-0">★</Badge>}
                                        <div className="flex items-center gap-0.5 opacity-0 group-hover/op:opacity-100 transition-opacity">
                                          {opGroups.length > 1 && (
                                            <button
                                              type="button"
                                              onClick={(e) => { e.stopPropagation(); openMoveOp(Number(item.id), op); }}
                                              className="p-0.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
                                              title="Переместить в другую группу"
                                            >
                                              <Move className="h-3 w-3" />
                                            </button>
                                          )}
                                          <button
                                            type="button"
                                            onClick={(e) => { e.stopPropagation(); deleteOp(Number(item.id), op.id, op.operation_name); }}
                                            className="p-0.5 rounded hover:bg-destructive/20 text-muted-foreground hover:text-destructive"
                                            title="Удалить"
                                          >
                                            <X className="h-3 w-3" />
                                          </button>
                                        </div>
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

        <details open className="border rounded-lg bg-card overflow-hidden self-start sticky top-2">
          <summary className="cursor-pointer select-none px-3 py-2 flex items-center gap-2 text-sm font-medium hover:bg-accent/40 transition-colors">
            <Layers className="h-4 w-4 text-muted-foreground" />
            <span className="flex-1">ГХП</span>
            <Badge variant="secondary" className="text-xs">{spgs.length}</Badge>
          </summary>
          <div className="border-t">
            <Table className="w-full">
              <thead>
                <tr>
                  <th className="py-1.5 px-2 text-left text-xs font-medium w-8"></th>
                  <th className="py-1.5 px-2 text-left text-xs font-medium">Название</th>
                  <th className="py-1.5 px-2 text-right text-xs font-medium w-10">Уч.</th>
                </tr>
              </thead>
              <tbody>
                {spgs.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="py-2 px-2 text-xs text-muted-foreground">
                      Нет ГХП
                    </td>
                  </tr>
                ) : (
                  spgs.map((spg) => (
                    <tr
                      key={spg.id}
                      onClick={() => openEditSpg(spg)}
                      className="cursor-pointer transition-colors hover:bg-accent/40"
                      style={spg.icon_color ? { backgroundColor: spg.icon_color + "0C" } : undefined}
                    >
                      <td className="py-1.5 px-2">
                        {spg.icon ? (
                          <span style={{ color: spg.icon_color || undefined }}>
                            {renderIcon(spg.icon, "h-4 w-4")}
                          </span>
                        ) : spg.icon_color ? (
                          <span className="inline-block size-4 rounded-full bg-current" style={{ color: spg.icon_color }} />
                        ) : null}
                      </td>
                      <td className="py-1.5 px-2 text-sm truncate" title={spg.name}>{spg.name}</td>
                      <td className="py-1.5 px-2 text-xs text-muted-foreground text-right tabular-nums">
                        {spg.sections?.length ?? 0}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </Table>
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
        onDelete={spgDialogMode === "edit" && editingSpg ? () => setDeleteSpgDialog({ id: editingSpg.id, name: editingSpg.name }) : undefined}
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
