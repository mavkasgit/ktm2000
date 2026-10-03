/**
 * Сколько воркеров Playwright в прогоне E2E — разбор аргумента (#289).
 *
 * Зачем отдельный модуль
 * ---------------------
 * Число воркеров — не только настройка Playwright: столько же должно быть
 * клонов БД (`e2e:prep --workers N`) и столько же backend'ов
 * (`scripts/run-e2e.mjs`, `E2E_WORKERS`). Прогон, у которого Playwright
 * запустил N воркеров, а клон один, — это ровно тот `TRUNCATE … CASCADE`,
 * который #289 убирает: соседний воркер сносит данные посреди теста, и
 * симптомом становятся флейки, а не ошибка.
 *
 * Поэтому нераспознанная форма **не** означает «воркер один». Молчаливый
 * откат в небезопасный режим опаснее отказа: человек написал `--workers 2`
 * и получил изоляцию одного воркера, не узнав об этом. Модуль лежит здесь по
 * той же причине, что `run-slots.mjs` и `run-lock.mjs`: разбор проверяется
 * тестом, не запуская Playwright.
 *
 * Что Playwright понимает (docs/test-cli, `-j <workers> | --workers <workers>`):
 * целое — число воркеров, `N%` — доля логических ядер CPU, без значения —
 * дефолт 50%. Клонов под процент и под дефолт не выдать, поэтому обе формы
 * отвергаются с текстом, что делать.
 */

/** Playwright: `-j` — короткая форма `--workers`. */
const SHORT = "-j";
const LONG = "--workers";

const HINT =
  "Клонов БД и backend'ов должно быть столько же, сколько воркеров (#289), " +
  "поэтому запускать прогон с нераспознанной формой нельзя: получился бы один клон " +
  "на несколько воркеров, а это неразделённые данные между ними. " +
  "Передайте целое число: `--workers=2` (или `--workers 2`, `-j 2`).";

/**
 * Значение после `--workers`/`-j` — или `null`, если аргумента не было.
 *
 * Бросает на нераспознанной форме (`-j2`, `--workers` без значения):
 * вернуться к одному воркеру молча нельзя.
 */
function readWorkersValue(extraArgs) {
  for (let i = 0; i < extraArgs.length; i += 1) {
    const arg = extraArgs[i];
    if (arg === LONG || arg === SHORT) {
      const value = extraArgs[i + 1];
      if (value === undefined) {
        throw new Error(
          `\`${arg}\` без значения: Playwright в этом случае берёт дефолтные 50% ` +
            `логических ядер, а клонов под них столько не выдать. ${HINT}`,
        );
      }
      return value;
    }
    if (arg.startsWith(`${LONG}=`)) return arg.slice(LONG.length + 1);
    if (arg.startsWith(`${SHORT}=`)) return arg.slice(SHORT.length + 1);
    // `-j2`, `--workers2`, `--workers…` — Playwright такую форму не понимает,
    // а молчаливый откат к одному воркеру здесь опаснее всего.
    if (arg.startsWith(SHORT) || arg.startsWith(LONG)) {
      throw new Error(`Нераспознанная форма \`${arg}\`. ${HINT}`);
    }
  }
  return null;
}

/**
 * Число воркеров прогона из аргументов после яруса.
 *
 * Без `--workers`/`-j` — 1 (дефолт конфига `playwright.config.ts`, и он же
 * дефолт `WORKERS` в `scripts/run-e2e.mjs`). Любая форма, из которой нельзя
 * получить точный счёт, — ошибка, а не единица.
 */
export function parseWorkersArg(extraArgs) {
  const raw = readWorkersValue(extraArgs);
  if (raw === null) return 1;

  if (!/^\d+$/.test(raw)) {
    const reason = raw.endsWith("%")
      ? `Процентная форма (\`${raw}\`) требует своей реализации: клонов БД под ` +
        `процент столько не выдать.`
      : `\`${raw}\` — не целое число воркеров.`;
    throw new Error(`${reason} ${HINT}`);
  }
  const workers = Number(raw);
  if (workers < 1) {
    throw new Error(`\`--workers=${raw}\` — воркер должен быть хотя бы один. ${HINT}`);
  }
  return workers;
}
