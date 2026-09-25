# Обязательная авто-передача после фиксации факта — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Убрать выбор оператора и всегда отправлять материал на следующий этап после успешной фиксации факта.

**Architecture:** Оставить backend-контракт `auto_transfer_next` и ручную страницу `/transfers` без изменений. В frontend completion-flow удалить пользовательское состояние и чекбокс, а single/group payload сформировать с постоянным `auto_transfer_next: true`; трансформирующие этапы также передают этот флаг, используя существующую серверную разбивку по выходным размерам.

**Tech Stack:** React 18.3, TypeScript, Vite, TanStack Query, Vitest, pytest.

**Spec:** GitHub issue #187.

## Global Constraints

- Не менять backend-контракт и поведение `complete_task`.
- Сохранить ручное создание передач на странице «Передачи между ГХП».
- Не затрагивать чужие незакоммиченные изменения.
- Для completion single и group использовать `auto_transfer_next: true`.
- Авто-передача должна использовать фактически проведённоеgood_quantity на backend.

---

### Task 1: Убрать UI-флаг авто-передачи

**Files:**
- Modify: `frontend/src/features/sections/components/TaskActionDrawer.tsx:1-20,52-114,425-445`
- Modify: `frontend/src/features/sections/pages/SectionsTasksPage.tsx:148-155,388-398,683-760,1264-1290`

**Interfaces:**
- `TaskActionDrawerProps` больше не принимает `autoTransferNext` и `setAutoTransferNext`.
- `SectionsTasksPage` отправляет постоянное значение `true` в `CompleteTaskInput` и `BulkCompleteEntry`.

- [ ] Удалить из `TaskActionDrawer` импорт `useEffect`, UI-компонент `Checkbox`, поля пропсов и destructuring.
- [ ] Удалить effect, который сбрасывал флаг для трансформирующих этапов.
- [ ] Удалить блок чекбокса и поясняющий текст из формы.
- [ ] Удалить состояние `autoTransferNext` и его сброс при открытии формы.
- [ ] В group entries заменить `auto_transfer_next: autoTransferNext` на `auto_transfer_next: true`.
- [ ] В single payload заменить `auto_transfer_next: autoTransferNext` на `auto_transfer_next: true`.
- [ ] Удалить передачу удалённых props в `<TaskActionDrawer>`.
- [ ] Запустить `npm --prefix frontend run build` и исправить только ошибки, вызванные этим изменением.

### Task 2: Проверить доменное поведение

**Files:**
- Modify: `CONTEXT.md:316-317,340-348` только если текущий текст описывает checkbox как пользовательский выбор.

**Interfaces:**
- Документация должна говорить, что фиксация факта автоматически передаёт фактически проведённоеgood_quantity на следующий межсекционный этап.
- Ручная передача через `/transfers` остаётся отдельным действием для последующего перемещения.

- [ ] Проверить существующие backend-тесты `test_auto_transfer_next_creates_per_output_transfers` и `test_auto_transfer_next_duplicate_output_size_does_not_overflow`.
- [ ] Запустить `npm run test:pytest -- -k auto_transfer_next` через штатный launcher.
- [ ] Запустить релевантные frontend unit-тесты, если они существуют для `features/sections`; отдельный тест для простого удаления UI-флага не создавать.
- [ ] Проверить `git diff --check`.

### Task 3: Проверка пользовательского пути

- [ ] Проверить, что ручной сценарий на странице «Передачи между ГХП» остался: `createTransfer` вызывается из `ReadyTransferRow` и `runTransferBatch`.
- [ ] Проверить, что форма фиксации факта больше не содержит текста «Снимите, если хотите управлять перемещением вручную».
- [ ] Проверить frontend build и backend auto-transfer tests повторно после всех правок.
- [ ] Зафиксировать в issue #187 фактические команды проверки и результат.
