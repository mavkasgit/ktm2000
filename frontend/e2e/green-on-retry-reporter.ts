/**
 * Репортер «зелёные не с первой попытки».
 *
 * Зачем
 * -----
 * `retries: 2` в CI делает прогон зелёным и на флейке: в списке такой тест —
 * одна зелёная строка, ровно как у честно прошедшего, и ничто в выводе не
 * говорит, что первая попытка была красной. Итог прогона «зелёный» после этого
 * нельзя читать как «всё работает» — а именно так его и читают.
 *
 * Что делает
 * ----------
 * `onTestEnd` приходит на КАЖДУЮ попытку, ретрайные в том числе, поэтому
 * «зелёный не с первой попытки» — это ровно `status === "passed"` при
 * `retry > 0`. Такие тесты копятся в памяти и печатаются списком в `onEnd`.
 *
 * Пустой список не печатается вовсе: предупреждение, которое появляется на
 * каждом чистом прогоне, через неделю перестают читать. Молчание здесь и
 * значит «флейков в этом прогоне не было».
 *
 * Код выхода НЕ меняется: флейк — повод разбираться, а не «красный прогон».
 * Иначе этот репортер стал бы вторым `--retries=0` и запрещённым маскирующим
 * приёмом с другой стороны.
 *
 * Где подключён
 * -------------
 * В `reporter` в [`../playwright.config.ts`](../playwright.config.ts) и в
 * списке `--reporter` в [`run-tier.mjs`](run-tier.mjs): флаг CLI заменяет
 * список из конфига целиком, и без него репортер не дошёл бы ни до одного
 * прогона, который реально делают.
 */

import type { Reporter, TestCase, TestResult } from "@playwright/test/reporter";

class GreenOnRetryReporter implements Reporter {
  /** Ключ теста → номер зелёной попытки (нумерация с 1, как её видит человек). */
  private readonly greenOnRetry = new Map<string, number>();

  /** Репортер пишет в stdout — иначе Playwright добавит свои подсказки. */
  printsToStdio(): boolean {
    return true;
  }

  onTestEnd(test: TestCase, result: TestResult): void {
    if (result.retry <= 0 || result.status !== "passed") return;
    // `titlePath` отдаёт путь от корня: проект → файл → describe'ы → название.
    // Проект в нём есть, поэтому один и тот же тест в двух ярусах — это две
    // разные строки, а не задвоение одной.
    const title = test.titlePath().filter(Boolean).join(" › ");
    const attempt = result.retry + 1;
    this.greenOnRetry.set(title, Math.max(this.greenOnRetry.get(title) ?? 0, attempt));
  }

  onEnd(): void {
    if (this.greenOnRetry.size === 0) return;
    const rows = [...this.greenOnRetry.entries()].sort(([a], [b]) => a.localeCompare(b, "ru"));
    console.log(
      `[e2e:retry] Зелёные не с первой попытки — ${rows.length}. Это флейк, а не зелёный прогон: разобрать.`,
    );
    for (const [title, attempt] of rows) {
      console.log(`[e2e:retry]   • ${title} — зелёной стала попытка ${attempt}`);
    }
  }
}

export default GreenOnRetryReporter;
