// ПРОТОТИП #143 (throwaway) — плавающая панель переключения вариантов.
// Стрелки/клавиши ←→ пишут ?variant= в URL (replace), чтобы вариант был
// реплицируемым и переживал перезагрузку. Не часть дизайна — визуально чужой.
import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { ChevronLeft, ChevronRight, FlaskConical } from "lucide-react";

export type PrototypeVariant = {
  key: string;
  name: string;
};

export const FINISHED_GOODS_VARIANTS: PrototypeVariant[] = [
  { key: "A", name: "Таблица + модалка, операции — главный блок" },
  { key: "B", name: "Список + карточка рядом, операции — вкладка" },
  { key: "C", name: "Плитки, состава на плитке, операций нет" },
];

export function PrototypeSwitcher({
  variants,
  current,
}: {
  variants: PrototypeVariant[];
  current: string;
}) {
  const [, setSearchParams] = useSearchParams();

  const cycle = (dir: 1 | -1) => {
    const idx = variants.findIndex((v) => v.key === current);
    const next = variants[(idx + dir + variants.length) % variants.length];
    setSearchParams((prev) => {
      const p = new URLSearchParams(prev);
      p.set("variant", next.key);
      return p;
    }, { replace: true });
  };

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) return;
      if (e.key === "ArrowLeft") cycle(-1);
      if (e.key === "ArrowRight") cycle(1);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [current, variants]);

  const active = variants.find((v) => v.key === current);

  return (
    <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 flex items-center gap-1 rounded-full bg-zinc-900 text-zinc-50 shadow-xl border border-zinc-700 px-2 py-1.5 select-none">
      <span className="flex items-center gap-1 pl-1.5 pr-1 text-amber-300" title="Прототип #143 — не продакшн">
        <FlaskConical className="h-4 w-4" />
      </span>
      <button
        type="button"
        onClick={() => cycle(-1)}
        className="rounded-full p-1.5 hover:bg-zinc-700"
        aria-label="Предыдущий вариант"
      >
        <ChevronLeft className="h-4 w-4" />
      </button>
      <span className="text-xs px-2 min-w-[280px] text-center">
        <span className="font-bold text-amber-300">{current}</span>
        {" — "}
        {active?.name}
      </span>
      <button
        type="button"
        onClick={() => cycle(1)}
        className="rounded-full p-1.5 hover:bg-zinc-700"
        aria-label="Следующий вариант"
      >
        <ChevronRight className="h-4 w-4" />
      </button>
    </div>
  );
}
