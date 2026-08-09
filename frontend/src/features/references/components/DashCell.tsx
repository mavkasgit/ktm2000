import React from "react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/shared/ui/tooltip";
import { cn } from "@/shared/utils/cn";

export function DashCell({ reason, danger }: { reason: string | null; danger?: boolean }) {
  const dash = <span className={cn("text-muted-foreground", danger && "text-destructive")}>—</span>;
  if (!reason) return dash;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="cursor-help">{dash}</span>
      </TooltipTrigger>
      <TooltipContent>{reason}</TooltipContent>
    </Tooltip>
  );
}
