import React, { useCallback, useEffect, useState } from "react";
import { Plus } from "lucide-react";
import * as API from "shared/api";
import * as UI from "shared/ui";
import { Button } from "@/shared/ui/Button";
import { EntityDialog, renderIcon } from "@/shared/ui/EntityDialog";
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogCancel, AlertDialogAction } from "@/shared/ui/AlertDialog";
import { toast } from "@/shared/ui/use-toast";
import type { EntityDialogField } from "@/shared/ui/EntityDialog";

type Section = {
  id?: string | number;
  code: string;
  name: string;
  description?: string | null;
  kind?: string;
  icon?: string | null;
  icon_color?: string | null;
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

const SECTION_FIELDS: Record<string, EntityDialogField> = {
  code: { type: "text", label: "Код", placeholder: "DRILL", required: true, rowGroup: "row1" },
  name: { type: "text", label: "Название", placeholder: "Сверловка", required: true, rowGroup: "row1" },
  kind: { type: "select", label: "Тип", required: true, options: KIND_OPTIONS },
  icon: { type: "icon", label: "Иконка" },
  icon_color: { type: "color", label: "Цвет" },
  description: { type: "text", label: "Описание", placeholder: "Необязательно" },
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
  if (!response.ok) throw new Error(`Failed to delete section: ${response.status}`);
}

export function SectionsPage() {
  const [items, setItems] = useState<Section[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogMode, setDialogMode] = useState<"add" | "edit">("add");
  const [editingItem, setEditingItem] = useState<Section | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setItems(await apiListSections());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

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
    const payload = {
      code: (values.code as string)?.trim(),
      name: (values.name as string)?.trim(),
      kind: values.kind as string,
      icon: (values.icon as string) || null,
      icon_color: (values.icon_color as string) || null,
      description: (values.description as string) || null,
    };

    if (dialogMode === "edit" && editingItem?.id) {
      await apiPatchSection(Number(editingItem.id), payload);
    } else {
      await apiCreateSection(payload);
    }
    setDialogOpen(false);
    await load();
  };

  const handleDelete = async () => {
    if (!editingItem?.id) return;
    try {
      await apiDeleteSection(Number(editingItem.id));
      toast({ title: "Удалено", description: `${editingItem.name} удалён`, variant: "success" });
      setDialogOpen(false);
      await load();
    } catch (e) {
      toast({ title: "Ошибка", description: e instanceof Error ? e.message : "Не удалось удалить", variant: "destructive" });
    } finally {
      setDeleteDialogOpen(false);
    }
  };

  const initialValues = dialogMode === "edit"
    ? {
        code: editingItem?.code ?? "",
        name: editingItem?.name ?? "",
        kind: editingItem?.kind ?? "production",
        icon: editingItem?.icon ?? "",
        icon_color: editingItem?.icon_color ?? "#3B82F6",
        description: editingItem?.description ?? "",
      }
    : { kind: "production" };

  return (
    <section style={{ display: "grid", gap: 12 }}>
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Участки</h2>
        <Button size="sm" onClick={openAdd}>
          <Plus className="h-4 w-4 mr-1" />
          Добавить участок
        </Button>
      </div>

      <EntityDialog
        fields={SECTION_FIELDS}
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
              Это действие нельзя отменить. Участок будет удалён навсегда.
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

      {error ? <div role="alert">{error}</div> : null}
      {loading ? <div>Загрузка...</div> : null}

      <div className="overflow-x-auto">
        <Table className="w-auto">
          <thead>
            <tr>
              <th className="py-3 px-4 text-left text-sm font-medium whitespace-nowrap">Иконка</th>
              <th className="py-3 px-4 text-left text-sm font-medium whitespace-nowrap">Название</th>
              <th className="py-3 px-4 text-left text-sm font-medium whitespace-nowrap">Код</th>
              <th className="py-3 px-4 text-left text-sm font-medium whitespace-nowrap">Тип</th>
              <th className="py-3 px-4 text-left text-sm font-medium">Описание</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item, i) => (
              <tr
                key={String(item.id ?? `${item.code}-${i}`)}
                className="cursor-pointer transition-colors"
                onClick={() => openEdit(item)}
                style={item.icon_color ? { backgroundColor: item.icon_color + "18" } : undefined}
                onMouseEnter={(e) => {
                  if (item.icon_color) (e.currentTarget as HTMLTableRowElement).style.backgroundColor = item.icon_color + "40"
                }}
                onMouseLeave={(e) => {
                  if (item.icon_color) (e.currentTarget as HTMLTableRowElement).style.backgroundColor = item.icon_color + "18"
                }}
              >
                <td className="py-3 px-4 text-sm">
                  {item.icon ? (
                    <span style={{ color: item.icon_color || undefined }}>
                      {renderIcon(item.icon, "h-6 w-6")}
                    </span>
                  ) : (
                    <span className="text-muted-foreground text-sm">—</span>
                  )}
                </td>
                <td className="py-3 px-4 text-sm whitespace-nowrap">{item.name}</td>
                <td className="py-3 px-4 text-sm whitespace-nowrap">{item.code}</td>
                <td className="py-3 px-4 text-sm whitespace-nowrap">{KIND_LABELS[item.kind ?? "production"] ?? item.kind ?? "-"}</td>
                <td className="py-3 px-4 text-sm">{item.description ?? "-"}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      </div>
    </section>
  );
}
