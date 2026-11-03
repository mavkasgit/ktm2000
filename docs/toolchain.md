# Тулчейн: чем проверяется и где закреплено

Сводка «какими инструментами и где мы проверяем» — одно место вместо разбросанных
строк в `AGENTS.md`, `docs/testing-guide.md` и телах workflow.

Таблица между маркерами **генерируется из `tools.json`**:

- пересобрать — `npm run toolchain:write`;
- проверить расхождение — `npm run check:registry` (краснеет, если документ
  отстал от реестра либо если строку внутри маркеров поправили руками).

Что значат колонки: «чем» и «закреплено где» — название инструмента и файл, где
стоит его версия; «где исполняется» — стадии (commit, push, gate, ci, test);
«блокирует» — ненулевой ли у проверки выход; «последний обзор» — дата, когда
запись сверяли с действительностью (порог актуальности — пункт 3 в
`docs/quality/criteria.md`).

Чего этот список не говорит: умеет ли проверка падать (см.
`docs/quality/gates.md`), почему отвергнуты другие инструменты
(`docs/quality/not-adopted.md`) и то, что наличие инструмента в списке ещё не
значит, что он ловит нужную вам ошибку.

<!-- tools:start -->
| id | чем | закреплено где | версия | где исполняется | блокирует | последний обзор |
| --- | --- | --- | --- | --- | --- | --- |
| `action-checkout` | actions/checkout (actions/checkout) | `.github/workflows` | `@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0` | ci | да | 2026-11-03 |
| `action-setup-node` | actions/setup-node (actions/setup-node) | `.github/workflows` | `@49933ea5288caeca8642d1e84afbd3f7d6820020 # v4.4.0` | ci | да | 2026-11-03 |
| `action-setup-python` | actions/setup-python (actions/setup-python) | `.github/workflows` | `@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0` | ci | да | 2026-11-03 |
| `action-upload-artifact` | actions/upload-artifact (actions/upload-artifact) | `.github/workflows` | `@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4.6.2` | ci | нет | 2026-11-03 |
| `ajv` | Ajv (ajv-validator/ajv) | `package.json` | `^8.20.0` | gate, ci | да | 2026-11-03 |
| `alembic` | Alembic (sqlalchemy-org/alembic) | `backend/requirements.txt` | `>=1.13.0` | ci, manual | да | 2026-11-03 |
| `concurrently` | concurrently (open-cli-tools/concurrently) | `package.json` | `^9.1.2` | manual | нет | 2026-11-03 |
| `coverage` | coverage.py (coveragepy/coveragepy) | `backend/requirements-dev.txt` | `7.16.2` | ci | да | 2026-11-03 |
| `eslint` | ESLint (eslint/eslint) | `frontend/package.json` | `^9.39.5` | gate, ci | да | 2026-11-03 |
| `lefthook` | Lefthook (evilmartians/lefthook) | `package.json` | `2.2.2` | commit, push | да | 2026-11-03 |
| `mise` | mise-en-place (jdx/mise) | `mise.toml` | `2026.10.12` | manual | нет | 2026-11-03 |
| `node` | Node.js (nodejs/node) | `mise.toml` | `24` | gate, ci | да | 2026-11-03 |
| `npm` | npm (npm/cli) | `package.json` | `>=10` | gate, ci | да | 2026-11-03 |
| `playwright` | Playwright (microsoft/playwright) | `frontend/package.json` | `^1.60.0` | gate, ci | да | 2026-11-03 |
| `postgres` | PostgreSQL (postgres/postgres) | `infra/compose` | `15-alpine` | gate, ci, manual | да | 2026-11-03 |
| `pytest` | pytest (pytest-dev/pytest) | `backend/requirements-dev.txt` | `9.1.1` | gate, ci | да | 2026-11-03 |
| `pytest-asyncio` | pytest-asyncio (pytest-dev/pytest-asyncio) | `backend/requirements-dev.txt` | `1.4.0` | gate, ci | да | 2026-11-03 |
| `pytest-testmon` | pytest-testmon (tarpas/pytest-testmon) | `backend/requirements-dev.txt` | `2.2.0` | manual | нет | 2026-11-03 |
| `pytest-xdist` | pytest-xdist (pytest-dev/pytest-xdist) | `backend/requirements-dev.txt` | `3.8.0` | gate, ci | да | 2026-11-03 |
| `python` | Python (python/cpython) | `mise.toml` | `3.12` | gate, ci | да | 2026-11-03 |
| `ruff` | Ruff (astral-sh/ruff) | `backend/requirements-dev.txt` | `0.16.9` | gate, ci | да | 2026-11-03 |
| `typescript` | TypeScript (microsoft/TypeScript) | `frontend/package.json` | `^5.7.2` | commit, gate, ci | да | 2026-11-03 |
| `vitest` | Vitest (vitest-dev/vitest) | `frontend/package.json` | `^3.2.7` | gate, ci | да | 2026-11-03 |
| `vitest-coverage-v8` | @vitest/coverage-v8 (vitest-dev/vitest) | `frontend/package.json` | `^3.2.7` | ci | нет | 2026-11-03 |
<!-- tools:end -->
