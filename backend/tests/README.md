# Running Tests

## All tests

```bash
# From project root — run everything:
npm run test:pytest
```

This command does:
1. `npm run test:db:up` — start test Postgres container
2. `npm run test:db:wait` — wait until healthy
3. `cd backend && pytest -q` — run all tests in hybrid mode (`PYTEST_DB_MODE=hybrid` by default)

## Step by step (for debugging)

```bash
npm run test:db:up
npm run test:db:wait
cd backend
pytest -q          # or pytest -v for verbose, pytest -k shopfloor for specific tests
cd ..
npm run test:db:down
```

## DB isolation mode (hybrid, single mode)

Tests use one unified strategy (no split into reusable/clean-start sets):

1. per-module temporary database: `ktm_test_<module>_<runid>`
2. per-test temporary schema: `t_<uuid8>`
3. `Base.metadata.create_all()` in that schema
4. drop schema after each test
5. drop module DB after module finish

Mode toggle:

- `PYTEST_DB_MODE=hybrid` (default and only supported mode)
- any other value fails fast with explicit error

## Important

- Do NOT append `2>&1 | tail ...` to pytest commands in this environment — it causes a stray `2` to be passed as a path argument to pytest, resulting in `ERROR: file or directory not found: 2` and 0 tests collected.
- If you need to filter output, run pytest first, then inspect results separately.
- Test bootstrap removes stale temporary DBs matching `ktm_test_%` (cleanup after crash/timeout).
- DB user must have `CREATEDB` rights for hybrid mode.
- Safety guards prevent destructive operations on non-test targets.

## Frontend build

```bash
npm --prefix frontend run build
```
