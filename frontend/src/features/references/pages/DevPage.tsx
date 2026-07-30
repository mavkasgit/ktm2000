import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { renderIcon } from "@/shared/ui/EntityDialog";
import { IconCalendarCode, IconCalendarClock, IconCalendarCheck, IconCalendarEvent } from "@tabler/icons-react";
import { listSections } from "@/shared/api/sections";
import { queryKeys } from "@/shared/api/queryKeys";
import { getErrorMessage } from "@/shared/api/client";

/**
 * Таблица участков из справочника (/sections): иконки, коды, названия и цвета
 * приходят с сервера — никаких литералов конкретного завода в коде.
 */
function SectionsReferenceTable() {
  const { data: sections, isLoading, isError, error } = useQuery({
    queryKey: queryKeys.sections.all(),
    queryFn: () => listSections(),
  });

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Загрузка справочника участков…
      </div>
    );
  }

  if (isError) {
    return (
      <p className="py-6 text-sm text-destructive">
        Не удалось загрузить справочник участков: {getErrorMessage(error)}
      </p>
    );
  }

  const sorted = [...(sections ?? [])].sort((a, b) => a.sort_order - b.sort_order || a.id - b.id);

  if (sorted.length === 0) {
    return <p className="py-6 text-sm text-muted-foreground">Справочник участков пуст.</p>;
  }

  return (
    <div>
      <table className="w-full border-collapse">
        <thead>
          <tr className="bg-muted">
            <th className="text-left px-4 py-2">#</th>
            <th className="text-left px-4 py-2">Иконка</th>
            <th className="text-left px-4 py-2">Код</th>
            <th className="text-left px-4 py-2">Название</th>
            <th className="text-left px-4 py-2">Тип</th>
            <th className="text-left px-4 py-2">Цвет</th>
            <th className="text-left px-4 py-2">Порядок</th>
            <th className="text-left px-4 py-2">Активен</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((s, i) => (
            <tr
              key={s.id}
              className="border-b"
              style={s.icon_color ? { backgroundColor: s.icon_color + "18" } : undefined}
            >
              <td className="px-4 py-2 text-muted-foreground">{i + 1}</td>
              <td className="px-4 py-2">
                {s.icon ? (
                  <span style={{ color: s.icon_color ?? undefined, fontSize: 20 }}>
                    {renderIcon(s.icon, "h-5 w-5")}
                  </span>
                ) : (
                  <span className="text-muted-foreground">—</span>
                )}
              </td>
              <td className="px-4 py-2 font-mono font-medium">{s.code}</td>
              <td className="px-4 py-2">{s.name}</td>
              <td className="px-4 py-2 font-mono text-sm">{s.type}</td>
              <td className="px-4 py-2">
                {s.icon_color ? (
                  <>
                    <span
                      className="inline-block w-6 h-6 rounded border align-middle"
                      style={{ backgroundColor: s.icon_color }}
                    />
                    <span className="ml-2 font-mono text-sm">{s.icon_color}</span>
                  </>
                ) : (
                  <span className="text-muted-foreground">—</span>
                )}
              </td>
              <td className="px-4 py-2 font-mono text-sm">{s.sort_order}</td>
              <td className="px-4 py-2">{s.is_active ? "Да" : "Нет"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FaviconCandidates() {
  const candidates = [
    { id: 1, name: "Календарь + код", icon: IconCalendarCode, color: "#3B82F6", desc: "План и спецификация" },
    { id: 2, name: "Календарь + часы", icon: IconCalendarClock, color: "#8B5CF6", desc: "Расписание и тайминг" },
    { id: 3, name: "Календарь + галочка", icon: IconCalendarCheck, color: "#10B981", desc: "Выполненный план" },
    { id: 4, name: "Календарь", icon: IconCalendarEvent, color: "#06B6D4", desc: "Классический календарь" },
    { id: 5, name: "Текущая (без иконки)", icon: null, color: "#F59E0B", desc: "Стандартная заглушка" },
  ];

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">Нажмите на иконку, чтобы увидеть превью в реальном размере фавиконки (16px, 32px)</p>
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-4">
        {candidates.map((c) => (
          <div key={c.id} className="flex flex-col items-center gap-2 p-4 border rounded-lg">
            {/* Large preview */}
            <div className="w-16 h-16 flex items-center justify-center rounded-lg" style={{ backgroundColor: c.color + "20" }}>
              {c.icon ? (
                <c.icon size={40} stroke={1.5} color={c.color} />
              ) : (
                <div className="w-10 h-10 rounded" style={{ backgroundColor: c.color }} />
              )}
            </div>
            {/* Real-size favicon previews */}
            <div className="flex items-center gap-3">
              {c.icon ? (
                <>
                  <c.icon size={16} stroke={1.5} color={c.color} />
                  <c.icon size={32} stroke={1.5} color={c.color} />
                </>
              ) : (
                <>
                  <div className="w-4 h-4 rounded-sm" style={{ backgroundColor: c.color }} />
                  <div className="w-8 h-8 rounded-sm" style={{ backgroundColor: c.color }} />
                </>
              )}
            </div>
            <span className="text-xs font-medium text-center">{c.name}</span>
            <span className="text-xs text-muted-foreground text-center">{c.desc}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

const DEV_SECTIONS: { id: string; title: string; component: React.ReactNode }[] = [
  {
    id: "sections-reference",
    title: "Справочник участков (с сервера)",
    component: <SectionsReferenceTable />,
  },
  {
    id: "favicon-candidates",
    title: "Варианты фавиконок (планирование)",
    component: <FaviconCandidates />,
  },
];

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
