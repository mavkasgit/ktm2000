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
| `action-checkout` | actions/checkout (actions/checkout) | `.github/workflows` | `@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1` | ci | да | 2026-11-18 |
| `action-setup-node` | actions/setup-node (actions/setup-node) | `.github/workflows` | `@949feb2413d6458794dcd2491c4babbbce0c15c1 # v7.1.0` | ci | да | 2026-11-18 |
| `action-setup-python` | actions/setup-python (actions/setup-python) | `.github/workflows` | `@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 # v7.1.0` | ci | да | 2026-11-18 |
| `action-upload-artifact` | actions/upload-artifact (actions/upload-artifact) | `.github/workflows` | `@cf430e030ddbb5b0abf93d22962f4752f3646cd9 # v7.0.2` | ci | нет | 2026-11-18 |
| `ajv` | Ajv (ajv-validator/ajv) | `package.json` | `^8.20.0` | gate, ci | да | 2026-11-03 |
| `alembic` | Alembic (sqlalchemy-org/alembic) | `backend/requirements.txt` | `>=1.13.0` | ci, manual | да | 2026-11-03 |
| `commitlint` | commitlint (conventional-changelog/commitlint) | `mise.toml` | `21.2.4` | commit | да | 2026-11-20 |
| `concurrently` | concurrently (open-cli-tools/concurrently) | `package.json` | `^10.0.7` | manual | нет | 2026-11-09 |
| `coverage` | coverage.py (coveragepy/coveragepy) | `backend/requirements-dev.txt` | `7.17.2` | ci | да | 2026-11-09 |
| `eslint` | ESLint (eslint/eslint) | `frontend/package.json` | `^9.39.5` | gate, ci | да | 2026-11-03 |
| `jactionlint` | jactionlint (jdx/jactionlint) | `mise.toml` | `2.4.0` | gate, ci | да | 2026-11-18 |
| `lefthook` | Lefthook (evilmartians/lefthook) | `package.json` | `2.2.2` | commit, push | да | 2026-11-03 |
| `mise` | mise-en-place (jdx/mise) | `mise.toml` | `2026.10.12` | manual | нет | 2026-11-03 |
| `node` | Node.js (nodejs/node) | `mise.toml` | `26.13.0` | gate, ci | да | 2026-11-09 |
| `npm` | npm (npm/cli) | `package.json` | `>=11` | gate, ci | да | 2026-11-09 |
| `osv-scanner` | osv-scanner (google/osv-scanner) | `mise.toml` | `2.7.0` | ci | нет | 2026-11-18 |
| `playwright` | Playwright (microsoft/playwright) | `frontend/package.json` | `^1.65.0` | gate, ci | да | 2026-11-09 |
| `postgres` | PostgreSQL (postgres/postgres) | `infra/compose` | `15-alpine` | gate, ci, manual | да | 2026-11-03 |
| `pytest` | pytest (pytest-dev/pytest) | `backend/requirements-dev.txt` | `9.2.0` | gate, ci | да | 2026-11-09 |
| `pytest-asyncio` | pytest-asyncio (pytest-dev/pytest-asyncio) | `backend/requirements-dev.txt` | `1.4.1.post1` | gate, ci | да | 2026-11-09 |
| `pytest-testmon` | pytest-testmon (tarpas/pytest-testmon) | `backend/requirements-dev.txt` | `2.3.0` | manual | нет | 2026-11-09 |
| `pytest-xdist` | pytest-xdist (pytest-dev/pytest-xdist) | `backend/requirements-dev.txt` | `3.8.0` | gate, ci | да | 2026-11-03 |
| `python` | Python (python/cpython) | `mise.toml` | `3.14.10` | gate, ci | да | 2026-11-09 |
| `ruff` | Ruff (astral-sh/ruff) | `backend/requirements-dev.txt` | `0.17.4` | gate, ci | да | 2026-11-19 |
| `rumdl` | rumdl (rvben/rumdl) | `mise.toml` | `0.3.2` | gate | да | 2026-11-20 |
| `typescript` | TypeScript (microsoft/TypeScript) | `frontend/package.json` | `^5.9.3` | commit, gate, ci | да | 2026-11-09 |
| `vitest` | Vitest (vitest-dev/vitest) | `frontend/package.json` | `^5.1.0` | gate, ci | да | 2026-11-09 |
| `vitest-coverage-v8` | @vitest/coverage-v8 (vitest-dev/vitest) | `frontend/package.json` | `^5.1.0` | ci | нет | 2026-11-09 |
<!-- tools:end -->
