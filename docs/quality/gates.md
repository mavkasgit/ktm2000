# Карта гейтов: что проверяется, где и чем доказано

Это не справочник «как красиво настроить», а реестр защит. У каждой строки есть
ответ на четыре вопроса: что ловит, где выполняется, блокирует ли и чем доказано,
что проверка умеет падать. Последний вопрос — критерий «Run or read» из
`docs/quality/criteria.md`: проверку, которую никогда не видели красной, нельзя
считать защитой — она может молчать годами.

Сверка списка машинная: `scripts/gate.mjs` сравнивает имена шагов с блоком ниже
и краснеет на расхождении в обе стороны. Добавить шаг в гейт и не внести его
сюда — красный прогон, а не «допишем потом».

<!-- gates-steps:start -->
| Шаг | Ярус | Что ловит | Где ещё | Блокирует | Красный ход |
|-----|------|-----------|---------|-----------|-------------|
| `pins` | fast | фактические версии языков против pin-файлов и engines | pre-push, локальный гейт | да | prove-checks 2026-11-03 |
| `registry` | fast | реестр инструментов против схем и закреплений | pre-push, локальный гейт | да | prove-checks 2026-11-03 |
| `codegraph-age` | fast | возраст codegraph-индекса против HEAD | локальный гейт | только в strict | prove-checks 2026-11-03 |
| `docs-links` | fast | битые ссылки и карды документации | pre-commit, CI docs.yml | да | prove-checks 2026-11-03 |
| `scripts-tests` | fast | юнит-тесты node-скриптов корня | CI docs.yml | да | prove-checks 2026-11-03 |
| `labels-check` | fast | сгенерированные подписи фронта сверены с бэкендом | CI migrations.yml | да | prove-checks 2026-11-03 |
| `seeds-validate` | fast | сиды справочников внутренне непротиворечивы | CI migrations.yml | да | prove-checks 2026-11-03 |
| `profile-settings-manifest` | fast | манифест профилей настроек совпадает с кодом | CI migrations.yml | да | prove-checks 2026-11-03 |
| `compose-audit` | fast | потолки логов, healthcheck и restart-политика в compose | локальный гейт | да | prove-checks 2026-11-03 |
| `test-hygiene` | fast | мёртвые импорты в тестах | CI backend-tests.yml | нет, report-only | exempt: ловит ruff F401 |
| `backend-test-count` | fast | pytest-набор не меньше записанного в baseline | CI backend-tests.yml | да | prove-checks 2026-11-03 |
| `ruff` | fast | линтер backend | pre-commit, CI ruff.yml | да | prove-checks 2026-11-03 |
| `frontend-types` | fast | типы продакшн-кода фронта | CI frontend-tests.yml | да | prove-checks 2026-11-03 |
| `frontend-types-e2e` | fast | типы e2e-спек | CI frontend-tests.yml | да | prove-checks 2026-11-03 |
| `frontend-lint` | fast | ESLint: архитектурные границы FSD | pre-commit, CI frontend-tests.yml | да | prove-checks 2026-11-03 |
| `backend-tests` | full | pytest backend (создаёт свою БД) | CI backend-tests.yml | да | prove-checks --heavy 2026-11-03 |
| `frontend-unit` | full | vitest с покрытием | CI frontend-tests.yml | да | prove-checks --heavy 2026-11-03 |
| `frontend-test-count` | full | vitest-набор не меньше записанного в baseline | CI frontend-tests.yml | да | prove-checks --heavy 2026-11-03 |
| `alembic-drift` | нет локально | дрейф миграций против heads | CI migrations.yml | в CI | exempt: локально не запускается |
| `e2e-smoke` | e2e | Playwright smoke на своём клоне базы | CI e2e-smoke.yml | в CI | exempt: отдельный ярус |
<!-- gates-steps:end -->

## Три яруса

| Команда | Состав | Ориентир по времени | Когда |
|---------|--------|---------------------|-------|
| `npm run gate:fast` | 14 шагов яруса fast | бюджет 60 с | перед push (он и есть хук pre-push) |
| `npm run gate` | fast + backend-tests + frontend-unit | минуты | перед коммитом значимой правки, и так же в CI |
| `npm run gate:e2e` | полный + Playwright smoke | минуты плюс слот семафора | отдельно: поднимает свой стенд |

В CI вызов идёт с `--strict`: шаг, недоступный локально, там краснеет, а не
печатается строкой missing. Локально missing — честная пометка, а не зелёный
итог: без этих проверок зелёный гейт не означает «всё как в CI».

## Чем доказана способность падать

`npm run prove-checks` для каждого шага вносит одно реальное нарушение,
запускает шаг через тот же гейт (`gate --only=<шаг>`), требует ненулевой выход и
узнаваемого текста, затем откатывает и требует чистого `git status`. Результат
пишется в `docs/quality/proven-checks.json`, а `gate --strict` сверяет покрытие:
шаг без доказанного красного хода — красный строкой prove-coverage.

Состояние на 2026-11-03: 15 шагов из 18 показали красный ход (13 лёгким набором,
backend-tests и frontend-unit — тяжёлым), 3 помечены exempt с причиной. Два из
них локально не запускаются: `alembic-drift` накатывал бы миграции на dev-БД
живого стенда владельца, `e2e-smoke` берёт слот машинного семафора и свой клон
базы. Третий — `test-hygiene`: сам шаг возвращает 0 при находках (report-only по
решению владельца, #386), краснеть ему не на чем, а блокирующую часть ловит
`ruff` F401, который пробником доказан.

Тяжёлые шаги идут всегда отдельным вызовом с `--heavy`: полный прогон стоил бы
столько, сколько суммарно идут pytest и vitest, и в обычный набор их не
включают.

## Хуки — удобство, не защита

`lefthook.yml` навешивает на pre-commit ruff, eslint и docs-links по
staged-файлам, на pre-push — gate:fast. Каждый из этих шагов живёт ещё и в
гейте, и в CI: проверка, существующая только в хуке, не считается включённой,
потому что хук пропускается одной переменной окружения. Установка, политика
пропуска и запрет авторевнов — в `docs/quality/hooks.md`.

## Чего здесь нет

- prod-развёртывание и миграции на живой стенде — `docs/deployment.md`;
- правила выбора инструментов и перечень отвергнутых —
  `docs/quality/criteria.md` и `docs/quality/not-adopted.md`;
- незакрытые дыры (спеллинг, поиск секретов, дрейф открытого API,
  статический анализ типов Python) названы в `docs/quality/not-adopted.md`
  отдельно от принятых решений: это отсутствие проверки, а не проверка.
