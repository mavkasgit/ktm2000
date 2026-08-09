import React from "react";
import { Card } from "@/shared/ui/card";
import type { HangerSettings } from "@/shared/api/hangerCalc";

export function HangerConstantsPanel({ settings }: { settings: HangerSettings }) {
  return (
    <Card className="p-3 text-sm">
      <div className="font-medium mb-1">Константы подвеса</div>
      <div className="flex flex-wrap gap-x-6 gap-y-1 text-muted-foreground">
        <span>Лимит площади: <b className="text-foreground">{settings.area_limit_m2} м²</b></span>
        <span>Рабочая длина клюшки: <b className="text-foreground">{settings.rod_length_mm} мм</b></span>
        <span>Зазор: <b className="text-foreground">{settings.gap_mm} мм</b></span>
        <span>Клюшек на подвесе: <b className="text-foreground">×{settings.rod_count}</b></span>
      </div>
      <div className="text-xs text-muted-foreground mt-1.5">
        По площади = ⌊{settings.area_limit_m2} / (периметр × длина / 10⁶)⌋ · По размеру = ⌊
        {settings.rod_length_mm} / (габарит + {settings.gap_mm})⌋ × {settings.rod_count} · Итог = min
      </div>
    </Card>
  );
}
