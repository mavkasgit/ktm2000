import { Badge, Button, Dialog, DialogContent, DialogHeader, DialogTitle } from "@/shared/ui";
import { WarehouseRemainder } from "@/shared/api/shopfloor";
import { Package, ArrowRight } from "lucide-react";

interface WarehouseRemaindersDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  remainders: WarehouseRemainder[];
  isLoading: boolean;
  onUseRemainder: (remainder: WarehouseRemainder) => void;
}

function fmtQty(value: string): string {
  const n = parseFloat(value);
  if (!Number.isFinite(n)) return "0";
  return String(Math.round(n));
}

export function WarehouseRemaindersDialog({
  open,
  onOpenChange,
  remainders,
  isLoading,
  onUseRemainder,
}: WarehouseRemaindersDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[720px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Package className="h-5 w-5" />
            Складские остатки
          </DialogTitle>
        </DialogHeader>

        {isLoading ? (
          <p className="text-sm text-muted-foreground py-4">Загрузка остатков...</p>
        ) : remainders.length === 0 ? (
          <p className="text-sm text-muted-foreground py-4">Остатков на складе нет</p>
        ) : (
          <div className="max-h-[500px] overflow-auto">
            <table className="w-full text-sm">
              <thead className="border-b bg-muted/50 sticky top-0 bg-background">
                <tr>
                  <th className="text-left p-2 font-medium">Продукт</th>
                  <th className="text-left p-2 font-medium">Участок</th>
                  <th className="text-left p-2 font-medium">Пройденные этапы</th>
                  <th className="text-right p-2 font-medium">Остаток</th>
                  <th className="text-center p-2 font-medium">Действие</th>
                </tr>
              </thead>
              <tbody>
                {remainders.map((remainder) => (
                  <tr key={remainder.id} className="border-b">
                    <td className="p-2">
                      <div className="font-medium">{remainder.product_sku}</div>
                      <div className="text-xs text-muted-foreground truncate max-w-[180px]">
                        {remainder.product_name}
                      </div>
                    </td>
                    <td className="p-2">
                      <div className="text-xs font-medium">{remainder.section_code}</div>
                      <div className="text-xs text-muted-foreground truncate max-w-[120px]">
                        {remainder.section_name}
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
                      <span className="font-semibold text-emerald-700">
                        {fmtQty(remainder.remainder_quantity)}
                      </span>
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
                ))}
              </tbody>
            </table>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
