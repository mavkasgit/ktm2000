# Final Verification Subagent Prompt

You are the final verification subagent. Your task is to inspect the entire KTM-flow system after all sprint work and decide whether it is ready for a commit/release candidate.

Do not implement new features unless a tiny fix is required to make an already-implemented feature work. Focus on verification, regression, and evidence.

Repository:
`C:\Users\user\VibeCoding\KTM-flow`

Verification steps:
1. Check repository state with `git status --short`.
2. Read recent commits with `git log --oneline -n 10`.
3. Run backend tests: `npm run test:pytest`.
4. Stop test DB after tests: `npm run test:db:down`.
5. Run frontend build: `npm --prefix frontend run build`.
6. Inspect public routes and API registration:
   - `backend/app/main.py`
   - `backend/app/api/routes/production_planning.py`
   - `backend/app/api/routes/shopfloor.py`
   - `frontend/src/app/Router.tsx`
7. Verify old flow still exists:
   - import endpoints,
   - plan/release endpoints,
   - execution rows endpoint,
   - old overview compatibility.
8. Verify new flow exists:
   - movement-backed shopfloor operations,
   - transfers and discrepancies,
   - defects and defect items,
   - decisions,
   - rework,
   - comments and attachments,
   - read APIs with history/aggregates where implemented.
9. Check for raw URLs or removed columns in execution UI:
   - no raw `/api/production-plans/.../preview` links in user-facing table,
   - no `Передано`, `% передачи`, `% брака` columns in execution drawer stage table.
10. Check for risky gaps:
   - missing idempotency enforcement,
   - missing concurrency protection,
   - direct cache writes outside service path,
   - migrations that drift from models,
   - tests accidentally using dev DB.

Expected final output:
- `Ready` or `Not ready`.
- Exact commands run and pass/fail result.
- Top blockers ordered by severity.
- Residual risks that can be accepted for the next sprint.
- Files that likely need follow-up.

Do not mark the system ready if:
- backend tests fail,
- frontend build fails,
- tests can still target dev DB,
- execution page shows removed transfer columns,
- the app cannot import shopfloor routes,
- migrations cannot run on a clean DB.
