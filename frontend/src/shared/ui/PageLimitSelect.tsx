import type { PageLimitOption } from "@/shared/hooks/usePaginatedTableQuery";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/shared/ui/Select";

const DEFAULT_PAGE_LIMIT_OPTIONS: PageLimitOption[] = [50, 100, 200, 500];

export interface PageLimitSelectProps {
  value: PageLimitOption;
  onValueChange: (limit: PageLimitOption) => void;
  options?: PageLimitOption[];
  className?: string;
}

export function PageLimitSelect({
  value,
  onValueChange,
  options = DEFAULT_PAGE_LIMIT_OPTIONS,
  className,
}: PageLimitSelectProps) {
  return (
    <Select
      value={String(value)}
      onValueChange={(v) => onValueChange(Number(v) as PageLimitOption)}
    >
      <SelectTrigger
        className={className ?? "h-7 w-[84px] text-xs bg-white"}
        aria-label="Количество записей на странице"
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((option) => (
          <SelectItem key={option} value={String(option)}>
            {option}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}