/**
 * PrintSheet.tsx — правила печати листа, одни на все окна печати.
 *
 * Механика одна: окно помечает себя `print-area`, лист внутри — `print-sheet`,
 * всё служебное (шапка окна, кнопки) — `no-print`; печатает браузер
 * (`window.print()`), а на лист попадает только лист. Правила жили строкой
 * внутри `PlanModal`; второй лист (передачи) получил бы свою копию, и вёрстка
 * печати разошлась бы по экранам — как расходилась до ADR-0038 вёрстка шапок.
 *
 * Ширина таблицы на печати — по содержимому (`fit-table`, см. ниже): превью
 * и бумага показывают одни и те же колонки, просто на листе кегль меньше.
 * План участка и «Передачи» печатаются одинаково — правило одно на оба.
 *
 * Многостраничный лист: колонтитул `@page` (`@bottom-center`) печатается на
 * каждой странице и несёт строку листа (её задаёт окно через
 * `footerPrefix`) и «Страница N из M». Разорванный лист поэтому не теряет
 * ни номер плана с датой, ни порядковый номер страницы. Механику считает
 * сам браузер, DOM о разбивке на страницы не знает.
 *
 * Две особенности, обе найдены печатью в Chromium 148, а не размышлением:
 *
 * - колонтитулу `@page` нужно поле снизу (здесь 7 мм), при `@page margin: 0`
 *   он не рисуется вовсе;
 * - `thead` с двумя строками (строка листа + подписи колонок) при наличии
 *   колонтитула повторяется только нижней строкой — на странице 2+ пропадает
 *   именно строка листа. Поэтому повтор шапки таблицы держим одной строкой,
 *   а идентификацию листа несёт колонтитул.
 *
 * Колонтитул `@page` рисуют Chromium/Edge 131+ и новее; Firefox и Safari его
 * не поддерживают — там лист печатается как раньше, без номеров страниц.
 */

/**
 * Ширина листа в окне: A4 landscape минус поля печати (`10mm 12mm` в правилах
 * выше) — 273 мм ≈ 1032 px при 96 dpi. Без потолка окно шириной в монитор
 * растягивало колонки: три колонки разъезжались на полтора метра, и пустота
 * внутри таблицы читалась как сломанная вёрстка, хотя на бумаге лист ровно
 * такой ширины и есть. На печати потолок не мешает: доступная ширина листа
 * и равна этим 273 мм.
 */
export const PRINT_SHEET_WIDTH_CLASS = "mx-auto w-full max-w-[1032px]";

export type PrintStylesProps = {
  /**
   * Строка листа для колонтитула каждой страницы: название, участок, дата
   * формирования. Пустая — в колонтитуле остаётся только номер страницы.
   */
  footerPrefix?: string;
};

/** Значение в строку CSS: кавычки и обратные слэши из названия участка. */
function cssString(value: string): string {
  return `"${value.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
}

export function PrintStyles({ footerPrefix }: PrintStylesProps = {}) {
  // Лист идёт в колонтитуле перед номером, поэтому разделитель — часть
  // значения: без названия (`""`) строка не начинается с висящего «·».
  const prefix = cssString(footerPrefix ? `${footerPrefix} · ` : "");

  return (
    <style>{`
      :root { --print-footer-prefix: ${prefix}; }
      @page {
        size: A4 landscape;
        margin: 0 0 7mm 0;
        @bottom-center {
          content: var(--print-footer-prefix) "Страница " counter(page) " из " counter(pages);
          font: 9pt sans-serif;
          color: #000;
        }
      }
      @media print {
        html, body { margin: 0 !important; padding: 0 !important; background: white !important; height: auto !important; overflow: visible !important; }
        body * { visibility: hidden; }
        .print-area, .print-area * { visibility: visible; }
        body > *:not(.print-area):not([data-radix-focus-guard]) { display: none !important; }
        .print-area { position: static !important; display: block !important; width: auto !important; max-width: none !important; max-height: none !important; overflow: visible !important; transform: none !important; box-shadow: none !important; border: none !important; padding: 0 !important; }
        .print-area > *:not(.print-sheet) { display: none !important; }
        .print-sheet { flex: none !important; overflow: visible !important; height: auto !important; max-height: none !important; padding: 10mm 12mm !important; }
        .print-sheet .no-print-col { display: none !important; }
        .print-sheet table { width: 100% !important; table-layout: fixed; border-collapse: collapse; font-size: 9pt; }
        .print-sheet table.fit-table { width: auto !important; table-layout: auto !important; max-width: 100% !important; }
        .print-sheet th, .print-sheet td { padding: 1mm 1.5mm !important; font-size: 9pt; line-height: 1.2; white-space: normal !important; max-width: none !important; overflow-wrap: anywhere; word-break: break-word; }
        .print-sheet tr { break-inside: avoid; }
        .print-sheet thead { display: table-header-group; }
        .no-print { display: none !important; }
      }
    `}</style>
  );
}
