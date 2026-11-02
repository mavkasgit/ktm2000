import * as React from "react";

import { cn } from "@/shared/utils/cn";

/**
 * Мобильная таблица: закреплённые колонки и свайп по всей поверхности (#343).
 *
 * Механика ровно двух вещей: горизонтальный скролл телефонной ширины и
 * «липкие» ячейки. Строки, колонки и обработчики остаются на странице —
 * «Передачи» и доска участка (#345) кладут своё содержимое внутрь, а примитив
 * отвечает за то, чтобы таблица не сжималась в кашу и листалась пальцем и
 * мышью.
 *
 * Почему не CSS-классы на месте: голая `overflow-x-auto` даёт скролл, но
 * мышью таблицу не подвинуть (браузер тащит только тачем), а «липкая»
 * колонка без непрозрачной подложки просвечивает уезжающими числами. Оба
 * правила живут здесь один раз.
 *
 * Ниже 768px (`max-md:`) — граница телефона в проекте: у доски участка это
 * `useMediaQuery("(min-width: 768px)")`, у шапки — `.page-header sm:flex-row`.
 * Классы с этим префиксом на десктоп не применяются вовсе, поэтому раскладка
 * большого экрана остаётся прежней.
 */

/**
 * Минимальная ширина таблицы на телефоне: без неё `w-full` сжимает семь
 * колонок в 320px, и «Действия» уезжают за край без возможности доскроллить
 * (сжимать уже нечего — переполнения нет).
 */
export const MOBILE_TABLE_MIN_WIDTH_CLASS = "max-md:min-w-[720px]";

/** Порог жеста в пикселях: меньше — это нажатие, а не перетаскивание. */
export const DRAG_THRESHOLD_PX = 8;

/**
 * Элементы, которые обязаны получать тап, фокус и ввод: с них жест не
 * начинается. Список — роли и теги, а не классы: кнопка без `button` на
 * странице тоже встречается (`role="button"` у Radix).
 */
const INTERACTIVE_SELECTOR = [
  "input",
  "textarea",
  "select",
  "button",
  "a[href]",
  "[contenteditable='true']",
  "[role='button']",
  "[role='link']",
  "[role='checkbox']",
  "[role='radio']",
  "[role='combobox']",
  "[role='slider']",
  "[role='switch']",
  "[role='spinbutton']",
].join(", ");

function isInteractiveTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false;
  return target.closest(INTERACTIVE_SELECTOR) !== null;
}

export type StickySide = "left" | "right";

export interface StickyCellOptions {
  /** Имя закреплённой колонки: попадает в `data-sticky` (E2E и «Участки»). */
  name: string;
  side: StickySide;
  /**
   * Ячейка шапки: она закреплена ещё и по вертикали (общий `sticky top-0`),
   * поэтому обязана лежать выше закреплённых ячеек тела — иначе на пересечении
   * строка тела перекрывает заголовок.
   */
  header?: boolean;
  /** Непрозрачная подложка и прочие уточнения страницы (тон строки, отступы). */
  className?: string;
}

export interface StickyCellProps {
  "data-sticky": string;
  className: string;
}

/**
 * Свойства закреплённой ячейки: имя для E2E, сторона и уровень.
 *
 * Подложку приносит страница (`className`): примитив не знает, в каком тоне
 * нарисована строка, но требование у него одно — фон обязан быть непрозрачным,
 * иначе под липкую ячейку видно уезжающее содержимое.
 */
export function stickyCell({ name, side, header = false, className }: StickyCellOptions): StickyCellProps {
  return {
    "data-sticky": name,
    className: cn(
      side === "left" ? "max-md:sticky max-md:left-0" : "max-md:sticky max-md:right-0",
      header ? "max-md:z-30" : "max-md:z-10",
      className,
    ),
  };
}

export interface TableSwipeOptions {
  /** Порог жеста в пикселях; по умолчанию `DRAG_THRESHOLD_PX`. */
  thresholdPx?: number;
}

export interface TableSwipeHandlers {
  onPointerDown: React.PointerEventHandler<HTMLElement>;
  onPointerMove: React.PointerEventHandler<HTMLElement>;
  onPointerUp: React.PointerEventHandler<HTMLElement>;
  onPointerCancel: React.PointerEventHandler<HTMLElement>;
  /**
   * Гасит клик, которым браузер завершает перетаскивание. Один раз: следующий
   * клик — снова обычное нажатие.
   */
  onClickCapture: React.MouseEventHandler<HTMLElement>;
}

export interface TableSwipe {
  handlers: TableSwipeHandlers;
  /** Таблица едет под указателем прямо сейчас (курсор «схватил»). */
  isDragging: boolean;
}

interface DragState {
  pointerId: number;
  startX: number;
  startY: number;
  startScrollLeft: number;
  /** Порог пройден: с этого момента жест — перетаскивание, а не нажатие. */
  moved: boolean;
}

/**
 * Свайп таблицы указателем.
 *
 * Мышь и перо тащат таблицу сами: браузер не листает overflow-контейнер
 * перетаскиванием мыши, поэтому `scrollLeft` считаем мы. Тач не трогаем —
 * горизонтальную панораму делает нативный `overflow-x: auto`, и вторая
 * реализация поверх неё дала бы двойной ход и дёрганье.
 *
 * Три правила, без которых жест ломает экран:
 * 1. Порог: сдвиг меньше `thresholdPx` — нажатие, и клик обязан дойти до
 *    строки (выбор в массовом режиме, раскрытие группы).
 * 2. После настоящего перетаскивания синтетический `click` гасится: иначе
 *    отпускание пальца за пределами строки «нажимало» бы то, что под ним.
 * 3. Поля ввода, кнопки и селекты не перехватываются вовсе: оператор обязан
 *    попасть в поле количества и набрать число.
 */
export function useTableSwipe({ thresholdPx = DRAG_THRESHOLD_PX }: TableSwipeOptions = {}): TableSwipe {
  const dragRef = React.useRef<DragState | null>(null);
  const suppressClickRef = React.useRef(false);
  const [isDragging, setIsDragging] = React.useState(false);

  const onPointerDown = React.useCallback<React.PointerEventHandler<HTMLElement>>((event) => {
    const element = event.currentTarget;
    // Новый жест всегда снимает чужое подавление: клик предыдущего жеста,
    // закончившегося вне таблицы, мог не прийти вовсе.
    suppressClickRef.current = false;
    if (event.button !== 0) return;
    // Панораму тача делает браузер (см. шапку хука).
    if (event.pointerType === "touch") return;
    // Тащить нечего: на десктопе таблица укладывается в ширину, и жест там
    // не должен даже начинаться — иначе он трогал бы выделение текста.
    if (element.scrollWidth <= element.clientWidth) return;
    if (isInteractiveTarget(event.target)) return;

    dragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      startScrollLeft: element.scrollLeft,
      moved: false,
    };
  }, []);

  const onPointerMove = React.useCallback<React.PointerEventHandler<HTMLElement>>(
    (event) => {
      const drag = dragRef.current;
      if (!drag || event.pointerId !== drag.pointerId) return;
      const dx = event.clientX - drag.startX;
      const dy = event.clientY - drag.startY;

      if (!drag.moved) {
        if (Math.abs(dx) < thresholdPx) return;
        // Вертикальный жест — это прокрутка страницы, а не таблицы.
        if (Math.abs(dy) > Math.abs(dx)) {
          dragRef.current = null;
          return;
        }
        drag.moved = true;
        suppressClickRef.current = true;
        setIsDragging(true);
        // Захват — только после порога: на нажатии он увёл бы `click` с ячейки
        // на контейнер, и строка перестала бы выбираться.
        event.currentTarget.setPointerCapture?.(event.pointerId);
      }

      event.preventDefault();
      event.currentTarget.scrollLeft = drag.startScrollLeft - dx;
    },
    [thresholdPx],
  );

  const endDrag = React.useCallback<React.PointerEventHandler<HTMLElement>>((event) => {
    const drag = dragRef.current;
    if (!drag || event.pointerId !== drag.pointerId) return;
    dragRef.current = null;
    if (drag.moved) {
      const element = event.currentTarget;
      try {
        if (element.hasPointerCapture?.(event.pointerId)) element.releasePointerCapture(event.pointerId);
      } catch {
        // Захват уже снят браузером (pointercancel) — отпускать нечего.
      }
    }
    setIsDragging(false);
  }, []);

  const onClickCapture = React.useCallback<React.MouseEventHandler<HTMLElement>>((event) => {
    if (!suppressClickRef.current) return;
    suppressClickRef.current = false;
    event.preventDefault();
    event.stopPropagation();
  }, []);

  return {
    isDragging,
    handlers: {
      onPointerDown,
      onPointerMove,
      onPointerUp: endDrag,
      onPointerCancel: endDrag,
      onClickCapture,
    },
  };
}

export interface MobileScrollTableProps extends React.HTMLAttributes<HTMLDivElement> {
  /**
   * Ref на скролл-контейнер. Тот же узел нужен виртуализации
   * (`VirtualizedTableBody`), поэтому ref приходит снаружи, а не живёт внутри.
   */
  scrollRef?: React.RefObject<HTMLDivElement>;
}

/**
 * Скролл-контейнер мобильной таблицы. Содержимое (`<table>`) кладёт страница:
 * примитив не знает ни колонок, ни строк.
 */
export function MobileScrollTable({ scrollRef, className, children, ...rest }: MobileScrollTableProps) {
  const swipe = useTableSwipe();

  return (
    <div
      {...rest}
      ref={scrollRef}
      data-mobile-scroll-table=""
      data-dragging={swipe.isDragging ? "" : undefined}
      className={cn(
        // Телефон: горизонтальный скролл включается явно. На десктопе класса
        // нет — контейнер остаётся таким, каким его объявила страница.
        "max-md:overflow-x-auto",
        // Край таблицы не должен тянуть за собой «назад» браузера.
        "max-md:overscroll-x-contain",
        swipe.isDragging ? "max-md:cursor-grabbing" : "max-md:cursor-grab",
        className,
      )}
      {...swipe.handlers}
    >
      {children}
    </div>
  );
}
