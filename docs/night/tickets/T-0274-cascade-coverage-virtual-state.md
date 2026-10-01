# T-0274 — покрытие при каскадном откате: виртуальное состояние остатков

Тикет: https://github.com/mavkasgit/ktm2000/issues/274
Ветка: `night/2026-10-01`, worktree `C:/Users/LogoPrint/VibeCoding/ktm2000-night`.

## Решение (подтверждено владельцем 2026-10-01, комментарий в тикете)

Одно виртуальное состояние остатков, проход по каскаду в обратном топологическом
порядке; компенсация узла применяется к виртуальным группам; проверка покрытия
смотрит на итог прохода. Проверка «узел против снимка до» удаляется.

## Проблема

`preview_reverse` проверял каждый узел каскада независимо против ТЕКУЩЕГО
состояния складов (`comp.check(...)` без моделирования). Корень цепочки
`complete → final_release → return_to_stock` отдал свой выпуск зависимым, поэтому
его компенсации не хватало покрытия — хотя откат зависимых (который идёт первым)
вернул бы материал в ту же группу. Preview отдавал ложный `CoverageShortfall`,
обходной путь — откатывать узлы по одному.

## Правка

1. `MirrorLedgerMixin.coverage_effect(entries)` (`stock_compensator.py`) — чистовой
   эффект компенсаций на ключи покрытия: −расход на `from_location`, +приход на
   `to_location`. Выделен из `forward_coverage_deficit` (D7-A) и переиспользуется.
2. `_coverage_deficit(..., adjustments=...)` — к текущему остатку добавляется
   виртуальный эффект уже пройденных компенсаций.
3. `check(..., coverage_adjustments=None)` — у `StockActionCompensator` и
   `StockCompensator`; контракт описан в `base.Compensator`.
4. `preview_reverse` (`service.py`) — вместо цикла «узел против снимка до»:
   `_reverse_topological_order` по узлам отката (тот же порядок, что у реального
   `reverse`), затем последовательный проход — проверка узла против
   `остаток + эффект пройденных`, после успешной проверки эффект узла
   добавляется в виртуальное состояние.

## Обязательное условие приёмки

Из `test_reverse_full_chain_cascade_topological_order` удалён засев остатка
(5 шт `MANUAL_IN` в группу своего этапа), которым тест обходил дефект. Теперь
preview обязан сам смоделировать возврат материала зависимыми узлами; в тесте
добавлены `assert not preview.blockers` и `assert preview.plan_token`.

## Доказательство

- Точечно `tests/reversal` — **82 passed, 1 warning in 54.04s** (включая
  каскадный тест без засева, откаты по одному узлу, `test_coverage_shortfall_blocks_reverse`
  с реально нехватающим покрытием).
- До правки (в `check` каскада передаётся `None` вместо виртуального состояния)
  каскадный тест падает ровно как в тикете:
  `assert not [Blocker(kind='coverage', node_id=1, detail='недостаточно покрытия…', deficit=Decimal('5.000'))]`.
- `ruff check backend/app/reversal backend/tests/reversal` — зелёный.
- Полный backend-прогон после правок #279 и #274 (под нагрузкой):
  **2000 passed, 3 warnings in 392.80s** (лог `logs/pytest-10d1cf169c26.log`).
- `assert_no_invariants_violations` вызывается в каскадном тесте (до и после
  отката) и в остальных тестах остатка — без изменений.

## Что НЕ трогали

- `preview_amend` / `reverse_amend` / реплей — их per-node проверки не менялись
  (вне скоупа тикета);
- `reverse()` — там проверка идёт по фактически применённому состоянию после
  каждой компенсации, это корректно и осталось как есть;
- семантика `_CoverageKey` (5 осей, ADR-0043/0055) и `_deficit_for`.

## Критерии готовности

- [x] каскад `complete → final_release` с частичной отгрузкой проходит без
  `CoverageShortfall` (без засева остатка);
- [x] откат по одному узлу не сломан (`test_reversal_core` — coverage-блокер на
  нехватке остаётся; 82 теста пакета зелёные);
- [x] `assert_no_invariants_violations` в тестах остатка;
- [x] полный прогон зелёный.

## Откат

`git revert <sha>`: затронуты `stock_compensator.py`, `action_compensator.py`,
`base.py`, `service.py` и тест; схем и миграций нет.
