import React from "react";
import { renderIcon } from "@/shared/ui/EntityDialog";
import { IconBlade, IconSpray, IconFlask2, IconAtom2, IconWashPress, IconBuildingFactory2, IconCut, IconWaveSawTool, IconWood, IconHammer, IconPick, IconAxe, IconScissors } from "@tabler/icons-react";

type SectionPreview = {
  code: string;
  name: string;
  icon: string;
  color: string;
};

const PROPOSED_SECTIONS: SectionPreview[] = [
  { code: "WH", name: "Склад сырья", icon: "Warehouse", color: "#F59E0B" },
  { code: "DRILL", name: "Сверловка", icon: "Drill", color: "#3B82F6" },
  { code: "PRESS", name: "Пресс", icon: "Anvil", color: "#EF4444" },
  { code: "SHOT", name: "Дробеструй", icon: "Fan", color: "#6B7280" },
  { code: "ANOD", name: "Анодирование", icon: "FlaskConical", color: "#06B6D4" },
  { code: "WIP_WH", name: "Склад полуфабриката", icon: "Boxes", color: "#84CC16" },
  { code: "SAW", name: "Пила", icon: "Axe", color: "#F97316" },
  { code: "PACK", name: "Упаковка", icon: "Package", color: "#10B981" },
  { code: "FG_WH", name: "Склад готовой продукции", icon: "Container", color: "#065F46" },
];

const SAW_ALTERNATIVES: SectionPreview[] = [
  { code: "", name: "Axe (топор)", icon: "Axe", color: "#F97316" },
  { code: "", name: "PenTool (инструмент)", icon: "PenTool", color: "#F97316" },
  { code: "", name: "Pickaxe (кирка)", icon: "Pickaxe", color: "#F97316" },
  { code: "", name: "Cog (шестерёнка)", icon: "Cog", color: "#F97316" },
  { code: "", name: "Wrench (ключ)", icon: "Wrench", color: "#F97316" },
];

const SHOT_ALTERNATIVES: SectionPreview[] = [
  { code: "", name: "Fan (вентилятор)", icon: "Fan", color: "#6B7280" },
  { code: "", name: "Cog (шестерёнка)", icon: "Cog", color: "#6B7280" },
  { code: "", name: "Construction (стройка)", icon: "Construction", color: "#6B7280" },
  { code: "", name: "Sparkles (искры)", icon: "Sparkles", color: "#6B7280" },
];

const ANOD_ALTERNATIVES: SectionPreview[] = [
  { code: "", name: "FlaskConical (колба)", icon: "FlaskConical", color: "#06B6D4" },
  { code: "", name: "Beaker (стакан)", icon: "Beaker", color: "#06B6D4" },
  { code: "", name: "TestTube (пробирка)", icon: "TestTube", color: "#06B6D4" },
  { code: "", name: "Droplets (капли)", icon: "Droplets", color: "#06B6D4" },
];

const FINAL_SECTIONS: SectionPreview[] = [
  { code: "WH", name: "Склад сырья", icon: "Warehouse", color: "#F59E0B" },
  { code: "DRILL", name: "Сверловка", icon: "Drill", color: "#3B82F6" },
  { code: "PRESS", name: "Пресс", icon: "Anvil", color: "#EF4444" },
  { code: "SHOT", name: "Дробеструй", icon: "SprayCan", color: "#6B7280" },
  { code: "ANOD", name: "Анодирование", icon: "FlaskConical", color: "#06B6D4" },
  { code: "WIP_WH", name: "Склад полуфабриката", icon: "Boxes", color: "#84CC16" },
  { code: "SAW", name: "Пила", icon: "Fan", color: "#F97316" },
  { code: "PACK", name: "Упаковка", icon: "Package", color: "#10B981" },
  { code: "FG_WH", name: "Склад готовой продукции", icon: "Container", color: "#065F46" },
];

function TablerIconsTable() {
  return (
    <div>
      <table className="w-full border-collapse">
        <thead>
          <tr className="bg-muted">
            <th className="text-left px-4 py-2">#</th>
            <th className="text-left px-4 py-2">Иконка</th>
            <th className="text-left px-4 py-2">Код</th>
            <th className="text-left px-4 py-2">Название</th>
            <th className="text-left px-4 py-2">Цвет</th>
          </tr>
        </thead>
        <tbody>
          {FINAL_SECTIONS.map((s, i) => {
            const iconKey = s.icon.replace("tabler:", "").replace("lucide:", "");
            const isLucide = s.icon.startsWith("lucide:");
            const isTabler = s.icon.startsWith("tabler:");
            const tablerMap = { Spray: IconSpray };
            const IconComp = isTabler ? tablerMap[iconKey] : null;
            return (
              <tr
                key={s.code + s.name + i}
                className="border-b"
                style={{ backgroundColor: s.color + "18" }}
              >
                <td className="px-4 py-2 text-muted-foreground">{i + 1}</td>
                <td className="px-4 py-2">
                  {isLucide ? (
                    <span style={{ color: s.color, fontSize: 20 }}>
                      {renderIcon(iconKey, "h-5 w-5")}
                    </span>
                  ) : isTabler && IconComp ? (
                    <span style={{ color: s.color, fontSize: 20 }}>
                      <IconComp size={20} />
                    </span>
                  ) : (
                    <span style={{ color: s.color, fontSize: 20 }}>
                      {renderIcon(iconKey, "h-5 w-5")}
                    </span>
                  )}
                </td>
                <td className="px-4 py-2 font-mono font-medium">{s.code}</td>
                <td className="px-4 py-2">{s.name}</td>
                <td className="px-4 py-2">
                  <span
                    className="inline-block w-6 h-6 rounded border align-middle"
                    style={{ backgroundColor: s.color }}
                  />
                  <span className="ml-2 font-mono text-sm">{s.color}</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const DEV_SECTIONS: { id: string; title: string; component: React.ReactNode }[] = [
  {
    id: "final-sections",
    title: "Итоговый вариант",
    component: <TablerIconsTable />,
  },
];

function SectionsIconsTable({ sections }: { sections: SectionPreview[] }) {
  return (
    <div>
      <table className="w-full border-collapse">
        <thead>
          <tr className="bg-muted">
            <th className="text-left px-4 py-2">#</th>
            <th className="text-left px-4 py-2">Иконка</th>
            <th className="text-left px-4 py-2">Код</th>
            <th className="text-left px-4 py-2">Название</th>
            <th className="text-left px-4 py-2">Цвет</th>
          </tr>
        </thead>
        <tbody>
          {sections.map((s, i) => (
            <tr
              key={s.code}
              className="border-b"
              style={{ backgroundColor: s.color + "18" }}
            >
              <td className="px-4 py-2 text-muted-foreground">{i + 1}</td>
              <td className="px-4 py-2">
                <span style={{ color: s.color, fontSize: 20 }}>
                  {renderIcon(s.icon, "h-5 w-5")}
                </span>
              </td>
              <td className="px-4 py-2 font-mono font-medium">{s.code}</td>
              <td className="px-4 py-2">{s.name}</td>
              <td className="px-4 py-2">
                <span
                  className="inline-block w-6 h-6 rounded border align-middle"
                  style={{ backgroundColor: s.color }}
                />
                <span className="ml-2 font-mono text-sm">{s.color}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DevPage() {
  return (
    <section className="p-8 space-y-8">
      <h1 className="text-xl font-semibold">Dev Page</h1>
      {DEV_SECTIONS.map((section) => (
        <div key={section.id} className="space-y-3">
          <h2 className="text-lg font-medium">{section.title}</h2>
          {section.component}
        </div>
      ))}
    </section>
  );
}
