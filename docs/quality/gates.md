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
| `registry` | fast | реестр инструментов против схем и закреплений, включая SHA действий в `.github/workflows/**` | pre-push, локальный гейт, CI ci-lint.yml | да | prove-checks 2026-11-03 |
| `freshness` | fast | возраст закреплений реестра: пин-файла нет — fail, пин не смотрели >180 дн. — warn | pre-push, cron freshness.yml (report-only) | только в strict и только по fail | prove-checks 2026-11-03 |
| `codegraph-age` | fast | возраст codegraph-индекса против HEAD | локальный гейт | только в strict | prove-checks 2026-11-03 |
| `docs-links` | fast | битые ссылки и карды документации | pre-commit, pre-push (docs), CI docs.yml | да | prove-checks 2026-11-03 |
| `docs-lint` | fast | структурные дефекты Markdown: fence без языка, списки, заголовки, битые относительные ссылки (rumdl, правила — `.rumdl.toml`) | pre-push (docs), локальный гейт | да | prove-checks 2026-11-20 |
| `adr-index` | fast | уникальность номеров ADR, шаблон заголовка, Дата/Статус | CI docs.yml | да | prove-checks 2026-11-03 |
| `scripts-tests` | fast | юнит-тесты node-скриптов корня | CI docs.yml | да | prove-checks 2026-11-03 |
| `labels-check` | fast | сгенерированные подписи фронта сверены с бэкендом | CI migrations.yml | да | prove-checks 2026-11-03 |
| `seeds-validate` | fast | сиды справочников внутренне непротиворечивы | CI migrations.yml | да | prove-checks 2026-11-03 |
| `profile-settings-manifest` | fast | манифест профилей настроек совпадает с кодом | CI migrations.yml | да | prove-checks 2026-11-03 |
| `compose-audit` | fast | потолки логов, healthcheck и restart-политика в compose | локальный гейт | да | prove-checks 2026-11-03 |
| `ci-lint` | fast | workflow GitHub Actions и `dependabot.yml`: схемы, выражения, пины, политики (jactionlint, флаг --strict-exit) | CI ci-lint.yml | да | prove-checks 2026-11-18 |
| `osv-allowlist` | fast | датированные исключения аудита зависимостей: запись без причины или с прошедшей датой пересмотра (сам скан — advisory в CI) | CI deps-audit.yml | да | prove-checks 2026-11-18 |
| `test-hygiene` | fast | мёртвые импорты в тестах | CI backend-tests.yml | нет, report-only | exempt: ловит ruff F401 |
| `backend-test-count` | fast | pytest-набор не меньше записанного в baseline | CI backend-tests.yml | да | prove-checks 2026-11-03 |
| `ruff` | fast | линтер backend | pre-commit, CI ruff.yml | да | prove-checks 2026-11-03 |
| `frontend-types` | fast | типы продакшн-кода фронта | CI frontend-tests.yml | да | prove-checks 2026-11-03 |
| `frontend-types-e2e` | fast | типы e2e-спек | CI frontend-tests.yml | да | prove-checks 2026-11-03 |
| `frontend-lint` | fast | ESLint: архитектурные границы FSD (ошибки) и потолок предупреждений по правилам и файлам — `npm run lint:ratchet` | pre-commit, CI frontend-tests.yml | да | prove-checks 2026-11-03: ошибки и рост предупреждений |
| `modern-web` | full | новые legacy-паттерны веб-платформы сверх базлайна `docs/quality/modern-web-baseline.json` | локальный гейт | да | prove-checks 2026-11-18 |
| `reactuse-diff` | fast | новые ручные `matchMedia`/clipboard/observers вместо ReactUse | локальный гейт | да | prove-checks 2026-11-18 |
| `backend-tests` | full | pytest backend (создаёт свою БД) | CI backend-tests.yml | да | prove-checks --heavy 2026-11-03 |
| `frontend-unit` | full | vitest с покрытием | CI frontend-tests.yml | да | prove-checks --heavy 2026-11-03 |
| `frontend-test-count` | full | vitest-набор не меньше записанного в baseline | CI frontend-tests.yml | да | prove-checks --heavy 2026-11-03 |
| `frontend-build` | full | сборка фронта и порог начального пакета (raw + gzip из `dist/index.html`, `frontend/bundle-size-baseline.json`) | CI frontend-tests.yml | да | prove-checks 2026-11-18: статический импорт страницы |
| `dev-deps` | full | dev-пакет фронтенда или корня, не названный ни в одном файле кода/конфига ни именем, ни бинарником (Markdown — не использование); report-only с 2026-11-03 до пересмотра 2027-05-01, в гейте — strict | CI frontend-tests.yml (report-only) | в strict локально; в CI — нет до пересмотра | prove-checks 2026-11-03 |
| `alembic-drift` | нет локально | дрейф миграций против heads | CI migrations.yml | в CI | exempt: локально не запускается |
| `e2e-smoke` | e2e | Playwright smoke на своём клоне базы | CI e2e-smoke.yml | в CI | exempt: отдельный ярус |
<!-- gates-steps:end -->

## Три яруса

| Команда | Состав | Ориентир по времени | Когда |
|---------|--------|---------------------|-------|
| `npm run gate:fast` | 21 шаг яруса fast | бюджет 60 с | `pre-commit` по staged-файлам; шаги fast — внутри `pre-push` по скоупу |
| `npm run gate` | fast + backend-tests + frontend-unit + frontend-build | минуты | перед merge глубокой работы; CI — фоновый второй взгляд |
| `npm run gate:e2e` | полный + Playwright smoke | минуты плюс слот семафора | отдельно: поднимает свой стенд |

С `--strict` шаг, недоступный локально, краснеет, а не печатается строкой
missing. Локально missing — честная пометка, а не зелёный итог: без этих
проверок зелёный гейт не означает «всё как в CI».

Тесты, типы, линтеры и сборки (`backend-tests`, `frontend-unit`,
`frontend-types`, `frontend-types-e2e`, `frontend-lint`, `frontend-build`,
`scripts-tests`, `ruff`) идут через задачи, а задачи берут слот машинного
семафора `heavy`
(корневой `AGENTS.md`, «Тяжёлые команды»): два агента на одной машине не
запускают pytest, `tsc`, линтер и сборку одновременно. Порядок шагов внутри
одного гейта не меняется — слот берётся на каждый шаг.

## Локальный гейт и режимы

Источник правды KTM — **локальный** гейт, а не GitHub. Причина: KTM живёт в
разных местах (GitHub, Gitea, GitLab, локальный сервер, приватный
`lab-shift-web`), и качество не должно зависеть от хостинга. GitHub Actions
остаётся фоновым вторым взглядом на push/PR; branch protection больше не требует
PR и required checks — только запрет force-push и удаления `main`. Это
сознательное отступление от workspace-правила «источник правды — CI»
(`harness/rules/quality-gates.md`): взамен действует жёсткий запрет обхода для
агентов и единственный критерий готовности — exit code гейта.

`pre-commit` остаётся быстрым и работает по staged-файлам (ruff, eslint,
docs-links, guard-tree). `pre-push`
([`scripts/ci/pre-push-gate.mjs`](../../scripts/ci/pre-push-gate.mjs)) смотрит
`git diff origin/main...HEAD` (fallback — `main`) и запускает только шаги
затронутой зоны:

| Diff | Скоуп | Что бежит | Замер |
|------|-------|-----------|-------|
| `docs/**`, `**.md` | `docs` | `docs-links`, `docs-lint`, `adr-index`, `ci-lint` | ~2 с |
| `backend/**` | `backend` | `pins`, `ruff`, `backend-tests`, `backend-test-count`, `test-hygiene`, `labels-check`, `seeds-validate`, `profile-settings-manifest` | ~4,5 мин |
| `frontend/**` | `frontend` | `pins`, `frontend-types`, `frontend-types-e2e`, `frontend-lint`, `frontend-unit`, `frontend-test-count`, `frontend-build`, `reactuse-diff`, `modern-web`, `dev-deps` | ~3 мин |
| обе зоны, `.github/**`, `scripts/**`, зависимости, неизвестный путь, нет базы | `full` | полный `npm run gate -- --strict` | ~7,6 мин |

Замеры — 2026-11-20 на этой машине. `alembic-drift` локально не запускается
(накатывает миграции на dev-БД) и остаётся за `migrations.yml`; `e2e` — отдельный
ярус `npm run gate:e2e`, в pre-push не входит. Неизвестный путь, пустой diff,
недоступная база и git-ошибка ведут в `full`, а не в «наверное, пронесёт».
`--strict` включён: шаг в статусе `missing` — красный, а не «не проверено».

### Два режима

| | Мелкий фикс | Глубокая работа |
|---|---|---|
| Где | прямо в `main` | локальная ветка или worktree |
| Коммит | `pre-commit` по staged-файлам | то же |
| Push | умный `pre-push`: только скоуп правки | `npm run gate -- --strict` до merge, затем merge в `main` и push (pre-push прогонит full) |
| CI | фон, можно не ждать | фон, можно не ждать |
| Время | ~2 с (docs) … ~4,5 мин (backend) | ~7,6 мин один раз перед merge |

Мелкий фикс по коду — это не «пропустить проверки»: бегут все шаги затронутой
зоны. Глубокая работа получает полный гейт один раз, а не на каждый коммит.

### Запрет обхода

Агенту запрещены `git commit --no-verify`, `git push --no-verify`, `LEFTHOOK=0`
и любое отключение хуков. Задача не готова, пока exit code гейта не `0`. Красный
хук — задача, а не помеха: правило не отключают и порог не ослабляют.
Человеку `--no-verify` остаётся аварийным выходом (инцидент на проде), с причиной
в PR/тикете; для агента это нарушение процесса, даже если код потом починили.

Обёртки проверены прогоном каждой задачи (2026-11-03): `npm run gate` —
все локальные шаги, `npm --prefix frontend run build` — 18.8 с,
`npm run test:scripts` — 94 теста, `npm run test:pytest -- -k dbcleaner` — 28
тестов. Единственный шаг, который сначала покраснел, — `frontend-test-count`:
из `run-slots.test.ts` убраны дубли `tryAcquireSlot`/`releaseSlot` (их теперь
проверяет `scripts/heavy-core.test.js`), поэтому baseline явно обновлён на
1531 и шаг позеленел.

Пока это цель, а не факт: полный `npm run gate -- --strict` в CI не
запускается — шаг `backend-tests` идёт через PowerShell-лаунчер с собственной
БД, которого на ubuntu-раннере нет. Но свой перечень проверок workflow больше
не хранят: каждый CI-шаг зовёт команду из `scripts/gate.mjs` через
`npm run gate -- --only=<шаг>` (#364), поэтому правка команды или порога живёт
в одном месте. Полный прогон `--strict` в CI — отдельный тикет.

## Рэтчет предупреждений ESLint (#372)

`frontend-lint` запускает не голый `eslint`, а `npm run lint:ratchet`
([`frontend/scripts/lint-ratchet.mjs`](../../frontend/scripts/lint-ratchet.mjs)).
Он считает предупреждения по правилам **и по файлам** и сверяет с
[`frontend/eslint-warnings-baseline.json`](../../frontend/eslint-warnings-baseline.json):

- рост числа (всего, по правилу или по файлу) — красный: накопить
  предупреждения незаметно нельзя, и переток «один файл починили, другой
  сломали» при неизменной сумме тоже виден;
- уменьшение — зелёный, потолок подтягивается той же правкой:
  `npm run lint:ratchet -- --update`; рост потолка — только явно
  `--update --force` и попадает в diff и в ревью;
- ошибки ESLint (`errorCount > 0`) и фатальный отказ линтера — красные:
  архитектурные границы FSD этим шагом не ослаблены, их проверяет тот же
  прогон (пробник `npm run prove-checks -- --only=frontend-lint`).

`npm run lint` остаётся ручным прогоном без потолка (быстрый взгляд),
`npm run lint:strict` (`eslint . --max-warnings=0`) — цель, а не гейт: он
станет обычным шагом, когда потолок дойдёт до нуля. Замер 2026-11-03:
48 предупреждений `react-hooks/exhaustive-deps` в 25 файлах при 0 ошибок.

## Чем доказана способность падать

`npm run prove-checks` для каждого шага вносит одно реальное нарушение,
запускает шаг через тот же гейт (`gate --only=<шаг>`), требует ненулевой выход и
узнаваемого текста, затем откатывает и требует чистого `git status`. Результат
пишется в `docs/quality/proven-checks.json`, а `gate --strict` сверяет покрытие:
шаг без доказанного красного хода — красный строкой prove-coverage.

Схема журнала здесь — вариант контракта `harness/rules/quality-gates.md`, и это
названо, а не подразумевается: вместо `checks[]` с `kind` — карта `steps{}`
(шаг → `proven_at`/`note`/`how`) плюс `exempt{}`. Причина: пробники живут в
`scripts/prove-checks.mjs`, а не в JSON, поэтому «патч» записи выражается кодом
пробника, а не полем `apply`; журнал остаётся результатом прогона, который
скрипт перезаписывает сам. Пробел варианта известен и не спрятан: у `exempt{}`
нет `reviewed`/`expires`, поэтому просрочка исключения машинно пока не ловится —
это отдельная работа по `exempt`, а не «отложенная автоматизация»: условие
появления — формат `exempt` с датами и шаг-хранитель, который краснеет на
прошедшей дате.

Состояние на 2026-11-18: 25 шагов из 28 показали красный ход (22 лёгким
набором, backend-tests, frontend-unit и frontend-test-count — тяжёлым),
3 помечены exempt с причиной. Два из
них локально не запускаются: `alembic-drift` накатывал бы миграции на dev-БД
живого стенда владельца, `e2e-smoke` берёт слот машинного семафора и свой клон
базы. Третий — `test-hygiene`: сам шаг возвращает 0 при находках (report-only по
решению владельца, #386), краснеть ему не на чем, а блокирующую часть ловит
`ruff` F401, который пробником доказан.

У шага, у которого красная только часть находок, пробник доказает ровно эту
часть. Так устроено у `freshness` (#368): краснеет он по флагу «пин-файла нет»,
а предупреждения — «закрепление не смотрели больше полугода», «вышла версия
свежее» — покраснеть не могут по определению. Их проверяют юниты
`scripts/freshness.test.js`: там и пороги, и выбор наихудшей из находок.

Тяжёлые шаги идут всегда отдельным вызовом с `--heavy`: полный прогон стоил бы
столько, сколько суммарно идут pytest и vitest, и в обычный набор их не
включают.

## Хуки — основной гейт, CI — зеркало

`lefthook.yml` навешивает на pre-commit ruff, eslint, docs-links и guard-tree по
staged-файлам, на commit-msg — `commitlint` (Conventional Commits, merge-коммиты
пропускаются), на pre-push — `scripts/ci/pre-push-gate.mjs` (скоуп по diff) плюс
`verify:sync`. Это не «удобство»: именно этот прогон решает, готово ли изменение,
а GitHub Actions — фоновый второй взгляд.

Честная граница: хук обходится одной клавиатурой, поэтому «100%» держится на
двух вещах — запрете обхода для агентов (AGENTS.md) и branch protection, которая
запрещает force-push и удаление `main`. Для человека аварийный `--no-verify`
остаётся, но каждая такая история объясняется в PR/тикете. Установка, политика
пропуска и запрет авторевнов — в `docs/quality/hooks.md`.

## Чего здесь нет

- prod-развёртывание и миграции на живой стенде — `docs/deployment.md`;
- правила выбора инструментов и перечень отвергнутых —
  `docs/quality/criteria.md` и `docs/quality/not-adopted.md`;
- незакрытые дыры (спеллинг, поиск секретов, дрейф открытого API,
  статический анализ типов Python) названы в `docs/quality/not-adopted.md`
  отдельно от принятых решений: это отсутствие проверки, а не проверка.
