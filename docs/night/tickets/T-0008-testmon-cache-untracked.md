# T-0008 — Кеш testmon оставляет untracked-файл в дереве

- **Категория:** гигиена конфигов тестов
- **Статус:** DONE (коммит `c2b5e1a`)
- **Дата:** 2026-10-01, цикл 2
- **Файлы (тестовая зона):** `.gitignore`, `docs/testing-guide.md`

## Проблема и доказательство

`npm run test:pytest:mon` (`--testmon`) пишет кеш в cwd, то есть в
`backend/.testmondata` (проверено: после двух прогонов `test:pytest:mon` файл
`backend/.testmondata` появился в дереве). В `.gitignore` есть
`.pytest_cache/` (строка 77) и `.coverage` (78), а `.testmondata` — нет:

```
$ git status --porcelain -uall
?? backend/.testmondata
```

То есть задокументированный режим «только изменённые тесты» пачкает рабочее
дерево: в `git status` появляется шум, а при неаккуратном `git add -A` кеш
уедет в коммит.

## План изменений

1. `.gitignore`: рядом с `.pytest_cache/`/`.coverage` добавить `.testmondata`
   и `.testmondata-journal` (журнал testmon на время прогона).
2. `docs/testing-guide.md`: в строке про `test:pytest:mon` отметить, что кеш
   лежит в `backend/.testmondata` и в git не попадает.

## Граница: что НЕ будет затронуто

- Продуктовый код, тесты, launcher, `pytest.ini` — не меняются.
- Правило `.gitignore` ничего не удаляет и не переопределяет; `--mon` работает
  как раньше (проверено: второй прогон выбирает 0 тестов).

## Критерии готовности (измеримые)

1. До: после `test:pytest:mon` в `git status --porcelain` появляется
   `?? backend/.testmondata`. После: тот же прогон — `git status` чист.
2. Кеш по-прежнему работает: первый прогон `--mon` выполняет тесты
   (`6 passed` на выборке `tests/test_e2e_stand.py`), второй — **0 тестов**
   (проверено в `logs/T-0009-testmon-1..2.log`).
3. Ни одного изменения вне `.gitignore` и `docs/testing-guide.md`.

## План отката

`git revert <commit>` (одна строка в `.gitignore` + строка документации).
