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

export function PrintStyles() {
  return (
    <style>{`
      @page { size: A4 landscape; margin: 0; }
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
