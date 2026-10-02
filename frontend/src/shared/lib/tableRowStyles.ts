/**
 * Shared table row styles — consistent hover and selection across all tables.
 */

export const TABLE_ROW_STYLES = {
  // Default rows
  defaultRow: "hover:bg-accent/60 hover:outline hover:outline-1 hover:outline-ring/30",
  defaultGroupRow: "hover:bg-accent/40 hover:outline hover:outline-1 hover:outline-ring/20",
  defaultGroupHeader:
    "bg-slate-100/70 hover:bg-slate-100 hover:outline hover:outline-1 hover:outline-slate-200 dark:bg-slate-800/50 dark:hover:bg-slate-800/80 dark:outline-slate-700",
  defaultGroupContainer: "bg-slate-50/30 dark:bg-slate-900/30",

  // Раскрытая группа на доске: строки внутри блока связаны, блоки разделены.
  // Внутренний разделитель тише обычного `border-b`, низ блока — заметнее:
  // граница проходит между группами, а не между строками одной группы.
  groupChildSeparator: "border-b border-slate-200/80 dark:border-slate-700/80",
  // Цвет границы нейтральный: статусные цвета заняты полосой строки и пилюлей,
  // а синий `border-blue-300` совпадал с «Передано» и читался как статус.
  groupBlockBoundary: "border-b-[3px] border-slate-300 dark:border-slate-600",
  // Подложка блока — та же, что у шапки группы: шапка и её строки читаются одним
  // куском, а не строкой с придатком. Тон задания здесь не используется: заливка
  // в тон строки делала пилюлю статуса неразличимой (амбер-бейдж на амбер-фоне),
  // а строки одной группы — разными по цвету. Цвет несёт полоса строки слева.
  groupBlock: "bg-slate-100/70 hover:bg-slate-200/60 dark:bg-slate-800/60 dark:hover:bg-slate-800/80",
  // Направляющая «шеврон → строки» и «строка → строка» внутри раскрытого блока.
  groupConnector: "bg-slate-300 dark:bg-slate-600",
  // Рёбра шапки группы — тоже на ячейках (границы `<tr>` в этой таблице не
  // рисуются): верх блока и линия между шапкой и её строками.
  groupHeaderCell: "border-y border-slate-200 dark:border-slate-700",

  // Selected rows (bulk)
  selectedRow: "bg-blue-100 ring-1 ring-blue-300 hover:bg-blue-200/80",
  selectedMobileCard: "bg-blue-100 border border-blue-300",

  // Selected group header
  selectedGroupHeader: "bg-blue-100/90 hover:bg-blue-200/70",
  selectedGroupContainer: "bg-blue-50/50",

  // Selection label
  selectedLabel: "text-blue-700 font-medium",

  // Ring for visual focus
  selectedRing: "ring-1 ring-blue-300",
} as const;
