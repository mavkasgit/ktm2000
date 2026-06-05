import { Badge, Button, Dialog, DialogContent, DialogHeader, DialogTitle } from "@/shared/ui";
import { SpgRemainder } from "@/shared/api/shopfloor";
import { Package, ArrowRight, Lock } from "lucide-react";
import { IconAlertTriangle } from "@tabler/icons-react";

interface SpgRemaindersDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  remainders: SpgRemainder[];
  isLoading: boolean;
  onUseRemainder: (remainder: SpgRemainder) => void;
  currentPlanPositionId?: number | null;
}

function fmtQty(value: string): string {
  const n = parseFloat(value);
  if (!Number.isFinite(n)) return "0";
  return String(Math.round(n));
}

export function SpgRemaindersDialog({
  open,
  onOpenChange,
  remainders,
  isLoading,
  onUseRemainder,
  currentPlanPositionId,
}: SpgRemaindersDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[720px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Package className="h-5 w-5" />
            Остатки в ГХП
          </DialogTitle>
        </DialogHeader>

        {isLoading ? (
          <p className="text-sm text-muted-foreground py-4">Загрузка остатков...</p>
        ) : remainders.length === 0 ? (
          <p className="text-sm text-muted-foreground py-4">Остатков в группах хранения нет</p>
        ) : (
          <div className="max-h-[500px] overflow-auto">
            <table className="w-full text-sm">
              <thead className="border-b bg-muted/50 sticky top-0 bg-background">
                <tr>
                  <th className="text-left p-2 font-medium">Продукт</th>
                  <th className="text-left p-2 font-medium">Группа хранения и производства (ГХП)</th>
                  <th className="text-left p-2 font-medium">Пройденные этапы</th>
                  <th className="text-right p-2 font-medium">Остаток</th>
                  <th className="text-center p-2 font-medium">Действие</th>
                </tr>
              </thead>
              <tbody>
                {remainders.map((remainder) => {
                  const qtyVal = parseFloat(remainder.remainder_quantity) || 0;
                  const isNegative = qtyVal < 0;
                  const isReservedForThis =
                    currentPlanPositionId != null &&
                    remainder.reserved_for_plan_position_id === currentPlanPositionId;
                  return (
                    <tr key={remainder.id} className={`border-b ${isReservedForThis ? "bg-amber-50 dark:bg-amber-950/20" : ""}`}>
                      <td className="p-2">
                        <div className="font-medium">{remainder.product_sku}</div>
                        <div className="text-xs text-muted-foreground truncate max-w-[180px]">
                          {remainder.product_name}
                        </div>
                        {isReservedForThis && (
                          <Badge
                            variant="outline"
                            className="mt-1 text-[9px] px-1.5 py-0 border-amber-500 text-amber-700 bg-amber-50 dark:bg-amber-950/30 dark:text-amber-400 inline-flex items-center gap-0.5"
                          >
                            <Lock size={8} />
                            Зарезервировано под эту задачу
                          </Badge>
                        )}
                      </td>
                      <td className="p-2">
                        <div className="text-xs font-medium">{remainder.spg_code}</div>
                        <div className="text-xs text-muted-foreground truncate max-w-[120px]">
                          {remainder.spg_name}
                        </div>
                      </td>
                      <td className="p-2">
                        <div className="flex flex-wrap gap-1 max-w-[200px]">
                          {remainder.completed_stages.slice(0, 3).map((stage, idx) => (
                            <Badge key={idx} variant="secondary" className="text-[10px] px-1.5 py-0">
                              #{stage.sequence} {stage.operation_name}
                            </Badge>
                          ))}
                          {remainder.completed_stages.length > 3 && (
                            <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                              +{remainder.completed_stages.length - 3}
                            </Badge>
                          )}
                        </div>
                      </td>
                      <td className="p-2 text-right">
                        <div className="flex items-center justify-end gap-1">
                          {isNegative && (
                            <span
                              title="Остаток ушёл в минус — требуется корректировка ручной операцией"
                              className="inline-block cursor-help"
                            >
                              <Badge
                                variant="destructive"
                                className="text-[9px] px-1 py-0 inline-flex items-center gap-0.5"
                              >
                                <IconAlertTriangle size={10} />
                                в минусе
                              </Badge>
                            </span>
                          )}
                          <span className={`font-semibold ${isNegative ? "text-amber-700" : "text-emerald-700"}`}>
                            {fmtQty(remainder.remainder_quantity)}
                          </span>
                        </div>
                        <div className="text-[10px] text-muted-foreground">
                          из {fmtQty(remainder.original_issued)}
                        </div>
                      </td>
                      <td className="p-2 text-center">
                        <Button
                          variant="outline"
                          size="sm"
                          className="text-xs h-7"
                          onClick={() => onUseRemainder(remainder)}
                        >
                          <ArrowRight className="h-3 w-3 mr-1" />
                          Использовать
                        </Button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

