import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { listSectionsWithOperations, type SectionWithOperations } from "@/shared/api/sections";
import { queryKeys } from "@/shared/api/queryKeys";
import { getErrorMessage } from "@/shared/api/client";
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/shared/ui";

const NONE_VALUE = "none";

type SectionOperationOption = SectionWithOperations["operations"][number];

export type RouteStepOperationSelectProps = {
  sectionId: number;
  operationCode: string | null;
  operationName: string;
  disabled?: boolean;
  onChange: (operation: { code: string | null; name: string }) => void;
};

/**
 * Выбор операции этапа маршрута. Коды и названия операций приходят из
 * справочника операций участков (/sections/all/operations) — никаких
 * литералов конкретного завода в коде.
 */
export function RouteStepOperationSelect({
  sectionId,
  operationCode,
  operationName,
  disabled = false,
  onChange,
}: RouteStepOperationSelectProps) {
  const { data: sectionsWithOps, isLoading, isError, error } = useQuery({
    queryKey: queryKeys.operations.all(),
    queryFn: listSectionsWithOperations,
  });

  if (isLoading) {
    return (
      <div className="mt-1 flex items-center gap-2 py-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Загрузка операций…
      </div>
    );
  }

  if (isError) {
    return (
      <p className="mt-1 py-2 text-sm text-destructive">
        Не удалось загрузить справочник операций: {getErrorMessage(error)}
      </p>
    );
  }

  const sectionOps =
    sectionsWithOps?.find((s) => s.id === sectionId)?.operations ?? [];

  // Код операции существующего маршрута может отсутствовать в актуальном
  // справочнике (операцию удалили/переименовали) — сохраняем его отдельным
  // пунктом, чтобы значение этапа не терялось при редактировании.
  const options: SectionOperationOption[] =
    operationCode && !sectionOps.some((op) => op.operation_code === operationCode)
      ? [
          ...sectionOps,
          {
            id: -1,
            operation_code: operationCode,
            operation_name: operationName || operationCode,
            is_significant: false,
            group_code: null,
            group_name: null,
          },
        ]
      : sectionOps;

  if (options.length === 0) {
    return (
      <p className="mt-1 py-2 text-sm text-muted-foreground">
        У участка нет операций в справочнике
      </p>
    );
  }

  return (
    <Select
      value={operationCode || NONE_VALUE}
      onValueChange={(val) => {
        const code = val === NONE_VALUE ? null : val;
        const op = options.find((o) => o.operation_code === code);
        onChange({ code, name: op?.operation_name || "" });
      }}
      disabled={disabled}
    >
      <SelectTrigger className="h-9 w-full bg-background mt-1">
        <SelectValue placeholder="Выберите операцию" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={NONE_VALUE}>Выберите операцию</SelectItem>
        {options.map((op) => (
          <SelectItem key={op.operation_code} value={op.operation_code}>
            {op.operation_name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
