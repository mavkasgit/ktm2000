# Running Tests

## All tests

```bash
# From project root — run everything:
npm run test:pytest
```

This command does:
1. `npm run test:db:up` — start test Postgres container
2. `npm run test:db:wait` — wait until healthy
3. `cd backend && pytest -q` — run all tests

## Step by step (for debugging)

```bash
npm run test:db:up
npm run test:db:wait
cd backend
pytest -q          # or pytest -v for verbose, pytest -k shopfloor for specific tests
cd ..
npm run test:db:down
```

## Important

- Do NOT append `2>&1 | tail ...` to pytest commands in this environment — it causes a stray `2` to be passed as a path argument to pytest, resulting in `ERROR: file or directory not found: 2` and 0 tests collected.
- If you need to filter output, run pytest first, then inspect results separately.

## Frontend build

```bash
npm --prefix frontend run build
```
