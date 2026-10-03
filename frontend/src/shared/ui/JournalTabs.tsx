import { NavLink, useInRouterContext } from "react-router-dom";

import { cn } from "@/shared/utils/cn";

/**
 * Переключатель вкладок раздела «Журнал».
 *
 * Живёт в `shared/ui`, потому что используется сразу двумя фичами
 * (`sections` и `reversal`), а cross-import между фичами запрещён FSD.
 *
 * Активная вкладка определяется маршрутом (`NavLink`), а не состоянием:
 * вкладка должна подсвечиваться и при прямом заходе по ссылке, и после
 * перезагрузки страницы.
 *
 * Вне контекста роутера (`NavLink` бросает инвариант) рендерим обычные
 * ссылки — так страницу можно unit-тестировать без обёртки-роутера.
 */
const TABS = [
  { to: "/audit-logs", label: "Действия" },
  { to: "/reversal", label: "Отмена действий" },
] as const;

const ACTIVE_CLASS = "rounded-md bg-white px-3 py-1.5 text-sm font-medium text-slate-800 shadow-sm";
const IDLE_CLASS = "rounded-md px-3 py-1.5 text-sm font-medium text-slate-500 transition-colors hover:text-slate-700";

export function JournalTabs() {
  const inRouter = useInRouterContext();

  return (
    <nav aria-label="Разделы журнала" className="flex gap-1 rounded-lg bg-slate-100 p-1">
      {TABS.map((tab) =>
        inRouter ? (
          <NavLink key={tab.to} to={tab.to} className={({ isActive }) => cn(isActive && ACTIVE_CLASS, !isActive && IDLE_CLASS)}>
            {tab.label}
          </NavLink>
        ) : (
          <a key={tab.to} href={tab.to} className={IDLE_CLASS}>
            {tab.label}
          </a>
        ),
      )}
    </nav>
  );
}
