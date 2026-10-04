## Исправление оркестратора: тикет был закрыт преждевременно

**Признание ошибки.** Комментарий о закрытии #312 был написан мной (оркестратором)
до того, как ветка `night/2026-10-03-312` была слита в `main`. Слияния не
произошло: `git merge-base --is-ancestor 0a48f8f5 main` возвращал `false`, а
`grep "_join_paired_component" backend/app/services/excel_import.py` в `main`
находил функцию на месте. **Код тикета отсутствовал в `main` целиком**, и
утверждение «закрыто» было ложным. Нашёл это при проверке состава прогона: спеки
`pair-article-cycle.spec.ts` в `main` не было.

**Что сделано сейчас:**
- ветка синхронизирована с `main` и слита: **`00b86567`**, 14 файлов;
- проверено на слитом дереве: `_join_paired_component` в `excel_import.py` — **0
  вхождений** (склейки больше нет), `resolve_pair_by_product_id` в
  `product_pair_resolver.py` — присутствует;
- `npm --prefix frontend run test` → **1340 passed / 1 skipped, 0 failed** (было
  1332 — прирост ровно на новые спеки #312: `PlanTaskTable` +3, `planTaskGroups` +5);
- `npx tsc -p tsconfig.json --noEmit` → 0 ошибок; `ruff check .` → All checks passed;
- pytest по зоне тикета (`test_excel_import`, `test_demo_full_route`,
  `test_migrations`, `test_product_composition`) → TESTS PASSED.

**Как это случилось — не для оправдания, а чтобы правило появилось.** Срез #312
отчитался «ветка готова к слиянию», и я закрыл тикет по его отчёту, не сверив
`git merge-base --is-ancestor` и содержимое `main`. Отчёт среза — утверждение о
его дереве, а не о `main`; слито или нет — проверяется на `main`. В утреннем
отчёте это теперь отдельный пункт в разделе «инциденты», а в
`PROMPT-TEMPLATE.md` добавлено правило: **закрытие тикета запрещено раньше, чем
коммит слит в `main` и проверен `git merge-base --is-ancestor <sha> main`.**