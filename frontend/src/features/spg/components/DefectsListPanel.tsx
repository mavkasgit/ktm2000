import { useState } from "react";
import { AlertCircle, Clock, CheckCircle, ShieldAlert, Plus, Search, ShieldCheck, Upload } from "lucide-react";

import { Button, Input, Badge } from "@/shared/ui";
import type { DefectOut } from "@/shared/api/defects";
import type { SpgOut, SpgRemainder } from "@/shared/api/spg";
import { CreateDefectDialog } from "./CreateDefectDialog";
import { DecideDefectDialog } from "./DecideDefectDialog";
import { ImportDefectsDialog } from "./ImportDefectsDialog";

interface DefectsListPanelProps {
  spgId: number;
  sections: SpgOut["sections"];
  remainders: SpgRemainder[];
  defects: DefectOut[];
  isLoading: boolean;
  onRefresh: () => void;
}

export function DefectsListPanel({
  spgId,
  sections,
  remainders,
  defects,
  isLoading,
  onRefresh,
}: DefectsListPanelProps) {
  const [createOpen, setCreateOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [decideOpen, setDecideOpen] = useState(false);
  const [selectedDefect, setSelectedDefect] = useState<DefectOut | null>(null);

  // Filters
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  const handleDecideClick = (defect: DefectOut) => {
    setSelectedDefect(defect);
    setDecideOpen(true);
  };

  const filteredDefects = defects.filter((d) => {
    const matchesSearch =
      !searchQuery.trim() ||
      d.product_sku.toLowerCase().includes(searchQuery.toLowerCase()) ||
      d.product_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (d.comment && d.comment.toLowerCase().includes(searchQuery.toLowerCase())) ||
      (d.created_by_user_name && d.created_by_user_name.toLowerCase().includes(searchQuery.toLowerCase()));

    const matchesStatus = statusFilter === "" || d.status === statusFilter;

    return matchesSearch && matchesStatus;
  });

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "decision_required":
        return (
          <Badge variant="outline" className="border-amber-500 text-amber-700 bg-amber-50 dark:bg-amber-950/20 inline-flex items-center gap-1">
            <Clock className="h-3 w-3" />
            Ожидает решения
          </Badge>
        );
      case "resolved":
        return (
          <Badge variant="outline" className="border-emerald-500 text-emerald-700 bg-emerald-50 dark:bg-emerald-950/20 inline-flex items-center gap-1">
            <ShieldCheck className="h-3 w-3" />
            Решено
          </Badge>
        );
      case "quality_hold":
        return (
          <Badge variant="outline" className="border-blue-500 text-blue-700 bg-blue-50 dark:bg-blue-950/20 inline-flex items-center gap-1">
            <ShieldAlert className="h-3 w-3" />
            Заморожено
          </Badge>
        );
      default:
        return <Badge variant="secondary">{status}</Badge>;
    }
  };

  const getDecisionTypeName = (type: string) => {
    switch (type) {
      case "scrap":
        return "Списание (Scrap)";
      case "accept_with_deviation":
        return "Принято с отклонением";
      case "quality_hold":
        return "Заморозка качества";
      default:
        return type;
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">
          Зарегистрированный брак ({filteredDefects.length} из {defects.length})
        </h3>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => setImportOpen(true)} className="inline-flex items-center gap-1">
            <Upload className="h-3.5 w-3.5" />
            Импортировать брак
          </Button>
          <Button size="sm" onClick={() => setCreateOpen(true)} className="inline-flex items-center gap-1">
            <Plus className="h-3.5 w-3.5" />
            Зарегистрировать брак
          </Button>
        </div>
      </div>

      {/* Search and Filters */}
      <div className="flex flex-col sm:flex-row items-center gap-2 bg-muted/10 p-2 rounded-lg border">
        <div className="relative w-full sm:flex-1">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Поиск по артикулу, названию, комментарию..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-background pl-9 h-9"
          />
        </div>
        <select
          className="w-full sm:w-[200px] rounded-md border border-input px-3 py-2 text-sm bg-background h-9 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="">Все статусы</option>
          <option value="decision_required">Ожидает решения</option>
          <option value="resolved">Решено</option>
          <option value="quality_hold">Заморожено</option>
        </select>
      </div>

      {isLoading ? (
        <p className="text-sm text-muted-foreground py-4 text-center">Загрузка дефектов...</p>
      ) : defects.length === 0 ? (
        <div className="text-center py-8 text-sm text-muted-foreground border rounded-lg border-dashed">
          Бракованной продукции в этой ГХП не зарегистрировано.
        </div>
      ) : (
        <div className="overflow-x-auto border rounded-lg">
          {filteredDefects.length === 0 ? (
            <div className="p-8 text-center text-sm text-muted-foreground">
              Нет записей брака, соответствующих фильтрам
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-muted/50 border-b">
                <tr>
                  <th className="p-2 text-left font-medium">№ / Дата</th>
                  <th className="p-2 text-left font-medium">Продукт</th>
                  <th className="p-2 text-right font-medium">Кол-во</th>
                  <th className="p-2 text-left font-medium">Причина</th>
                  <th className="p-2 text-left font-medium">Участок / Операция</th>
                  <th className="p-2 text-center font-medium">Источник</th>
                  <th className="p-2 text-center font-medium">Статус</th>
                  <th className="p-2 text-center font-medium">Решения</th>
                  <th className="p-2 text-center font-medium">Действия</th>
                </tr>
              </thead>
              <tbody>
                {filteredDefects.map((d) => {
                  const dateStr = new Date(d.created_at).toLocaleString();
                  const stepName = d.route_stage
                    ? `Шаг ${d.route_stage.sequence}: ${d.route_stage.operation_name}`
                    : "Без привязки к этапу";

                  return (
                    <tr key={d.id} className="border-b hover:bg-muted/30 align-top">
                      <td className="p-2 whitespace-nowrap text-xs">
                        <div className="font-semibold">#{d.id}</div>
                        <div className="text-muted-foreground text-[10px]">{dateStr}</div>
                        {d.created_by_user_name && (
                          <div className="text-muted-foreground mt-1 text-[10px] font-medium">
                            Автор: {d.created_by_user_name}
                          </div>
                        )}
                      </td>
                      <td className="p-2 max-w-[200px]">
                        <div className="font-medium text-xs truncate" title={d.product_sku}>
                          {d.product_sku}
                        </div>
                        <div className="text-[10px] text-muted-foreground truncate" title={d.product_name}>
                          {d.product_name}
                        </div>
                        {d.spg_remainder_id && (
                          <Badge variant="outline" className="text-[9px] h-4 mt-1 px-1 bg-purple-50/50">
                            Партия #{d.spg_remainder_id}
                          </Badge>
                        )}
                      </td>
                      <td className="p-2 text-right font-bold text-rose-600 whitespace-nowrap text-xs">
                        {d.total_quantity} шт.
                      </td>
                      <td className="p-2 text-xs">
                        <span className="font-medium bg-rose-50 text-rose-800 dark:bg-rose-950/20 dark:text-rose-300 px-1.5 py-0.5 rounded text-[10px] border border-rose-200">
                          {d.reason || "Не указан"}
                        </span>
                        {d.comment && (
                          <p className="text-[10px] text-muted-foreground mt-1.5 italic bg-muted/20 p-1 rounded border">
                            "{d.comment}"
                          </p>
                        )}
                      </td>
                      <td className="p-2 text-xs">
                        <div className="font-medium">{d.section_code}</div>
                        <div className="text-muted-foreground text-[10px]">{stepName}</div>
                      </td>
                      <td className="p-2 text-center text-xs whitespace-nowrap">
                        {d.task_id ? (
                          <Badge variant="secondary" className="text-[10px]">
                            Задание #{d.task_id}
                          </Badge>
                        ) : (
                          <Badge variant="outline" className="text-[10px]">
                            Вручную
                          </Badge>
                        )}
                      </td>
                      <td className="p-2 text-center">{getStatusBadge(d.status)}</td>
                      <td className="p-2 max-w-[220px]">
                        {d.decisions && d.decisions.length > 0 ? (
                          <div className="space-y-1 text-[10px]">
                            {d.decisions.map((dec) => (
                              <div
                                key={dec.id}
                                className="p-1 rounded bg-emerald-50/50 dark:bg-emerald-950/10 border border-emerald-100 dark:border-emerald-900/30 text-emerald-800 dark:text-emerald-300"
                              >
                                <div className="font-semibold flex justify-between gap-2">
                                  <span>{getDecisionTypeName(dec.decision_type)}</span>
                                  <span>{dec.quantity} шт.</span>
                                </div>
                                {dec.comment && <div className="italic text-muted-foreground">"{dec.comment}"</div>}
                                <div className="text-[9px] text-muted-foreground text-right mt-0.5">
                                  {new Date(dec.decided_at).toLocaleDateString()}
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <span className="text-[10px] text-muted-foreground">—</span>
                        )}
                      </td>
                      <td className="p-2 text-center whitespace-nowrap">
                        {d.status === "decision_required" ? (
                          <Button size="sm" onClick={() => handleDecideClick(d)} className="text-xs h-7 px-2 bg-amber-600 hover:bg-amber-700 text-white">
                            Решение
                          </Button>
                        ) : (
                          <span className="text-[11px] text-muted-foreground">Решено</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Dialogs */}
      <CreateDefectDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        spgId={spgId}
        sections={sections}
        remainders={remainders}
        onSaved={onRefresh}
      />

      <ImportDefectsDialog
        open={importOpen}
        onOpenChange={setImportOpen}
        spgId={spgId}
        onSaved={onRefresh}
      />

      {selectedDefect && (
        <DecideDefectDialog
          open={decideOpen}
          onOpenChange={setDecideOpen}
          defect={selectedDefect}
          onSaved={onRefresh}
        />
      )}
    </div>
  );
}
