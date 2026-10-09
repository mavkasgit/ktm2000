"""Сторож «компенсационная арифметика — только в ledger» (ADR-0017, DoD #110).

``net_quantity_expr()`` (``app/stock/ledger.py``) — единственный источник
компенсационной арифметики: знак строки ledger определяется там (запись с
``reverses_id`` вычитается из нетто, а не исключается скомпенсированная
исходная). Потребители обязаны переиспользовать примитив, а не пересчитывать
знак из ``reverses_id`` сами.

Сторож сканирует AST ``backend/app/**/*.py`` (кроме самого ``ledger.py``) и
падает на формах пересчёта знака:

* ``case(...)``, в поддереве которого есть и ``reverses_id``, и ``quantity`` —
  копия нетто-формулы;
* тернарник (``IfExp``), чьё условие смотрит на ``reverses_id``, а ветка даёт
  знак (±1 / ``-quantity``) — «свой знак» (ровно форма, удалённая в #317);
* ``BinOp`` (``*``/``+``/``-``) или унарный минус, в который входит
  ``reverses_id`` — прямая арифметика по компенсации.

Легитимные и НЕ арифметические использования ``reverses_id`` сторож не трогает
и перечисляет явно:

* фильтр активных проводок UI-журнала (`app/stock/api.py`, ветка
  ``compensating``: ``reverses_id.is_/is_not(None)``);
* write-side выбор активной проводки при компенсации/реплее передачи
  (`app/reversal/stock_compensator.py` — ``MirrorLedgerMixin._generation``,
  ``StockCompensator.apply_forward``, ``build_replay_payload``);
* зеркальная запись ``reverses_id=<source>`` и чтение исходной проводки по
  ``cmd.reverses_id`` (`app/stock/services.py`, `app/reversal/*`).

Тикет #317 называет write-side исключением как ``_compensate_transfer_stock_tx``;
функции с таким именем в дереве нет — фактическая точка та же (выбор активной
SEND-проводки в `app/reversal/stock_compensator.py`), и она не арифметика.

Тесты в скоуп сторожа НЕ входят: `backend/tests/test_integrity_invariants.py`
держит сырой SQL как независимый оракул (#111), а
`backend/tests/stock/test_task_cache_stage4.py::_sql_net_transactions` —
явно помеченный независимый оракул, а не потребитель примитива.
"""
from __future__ import annotations

import ast
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "app"
LEDGER_PATH = APP_DIR / "stock" / "ledger.py"

_CASE_CALLS = {"case"}
_SIGN_OPERATORS = (ast.Mult, ast.Add, ast.Sub)
_SIGN_LITERALS = {-1, 1}


def _call_name(func: ast.AST) -> str | None:
    """Имя вызываемого: ``case(...)`` или ``func.case(...)``."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _mentions(node: ast.AST, name: str) -> bool:
    """Есть ли в поддереве ссылка ``name`` (атрибут/имя/kwarg), но не строкой.

    Строковые литералы (каталоги, ``postgresql_include``) намеренно не считаем
    упоминанием: они не интерпретируют ``reverses_id``.
    """
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute) and child.attr == name:
            return True
        if isinstance(child, ast.Name) and child.id == name:
            return True
        if isinstance(child, ast.keyword) and child.arg == name:
            return True
    return False


def _has_sign_token(node: ast.AST) -> bool:
    """Есть ли в поддереве ±1 или унарный минус (носитель знака)."""
    for child in ast.walk(node):
        if isinstance(child, ast.UnaryOp) and isinstance(child.op, ast.USub):
            return True
        if (
            isinstance(child, ast.Constant)
            and isinstance(child.value, (int, float))
            and not isinstance(child.value, bool)
            and child.value in _SIGN_LITERALS
        ):
            return True
    return False


def _offenses(source: str, rel: str) -> list[str]:
    """Формы компенсационной арифметики в исходнике; пусто — чисто."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and _call_name(node.func) in _CASE_CALLS:
            if _mentions(node, "reverses_id") and _mentions(node, "quantity"):
                found.append(
                    f"{rel}:{node.lineno}: case() по reverses_id пересчитывает нетто"
                )
        elif isinstance(node, ast.IfExp):
            if _mentions(node.test, "reverses_id") and (
                _mentions(node.body, "quantity")
                or _mentions(node.orelse, "quantity")
                or _has_sign_token(node.body)
                or _has_sign_token(node.orelse)
            ):
                found.append(
                    f"{rel}:{node.lineno}: тернарник выводит знак из reverses_id"
                )
        elif isinstance(node, ast.BinOp) and isinstance(node.op, _SIGN_OPERATORS):
            if _mentions(node, "reverses_id"):
                found.append(
                    f"{rel}:{node.lineno}: reverses_id участвует в арифметике"
                )
        elif (
            isinstance(node, ast.UnaryOp)
            and isinstance(node.op, ast.USub)
            and _mentions(node.operand, "reverses_id")
        ):
            found.append(
                f"{rel}:{node.lineno}: унарный минус по reverses_id"
            )
    return found


def _app_modules() -> list[Path]:
    """Модули ``backend/app`` в скоупе сторожа — всё, кроме ledger-примитива."""
    return sorted(
        path for path in APP_DIR.rglob("*.py") if path.resolve() != LEDGER_PATH
    )


def test_no_compensation_arithmetic_outside_ledger() -> None:
    problems: list[str] = []
    for path in _app_modules():
        rel = path.relative_to(APP_DIR).as_posix()
        problems.extend(_offenses(path.read_text(encoding="utf-8"), rel))
    assert not problems, (
        "Компенсационная арифметика вне stock/ledger.py (ADR-0017, #317):\n"
        + "\n".join(problems)
    )


def test_ledger_is_the_single_owner_and_thus_exempt() -> None:
    """Примитив — владелец формулы: он её содержит и сторожем исключён по пути."""
    assert _offenses(LEDGER_PATH.read_text(encoding="utf-8"), "stock/ledger.py"), (
        "ledger обязан содержать нетто-формулу — иначе исключение сторожа бессмысленно"
    )
    assert LEDGER_PATH not in _app_modules()


def test_guard_flags_copied_case_formula() -> None:
    """Мутация: копия нетто-формулы обязана ломать сторожа."""
    mutant = (
        "def f():\n"
        "    return case(\n"
        "        (StockTransaction.reverses_id.is_(None), StockTransaction.quantity),\n"
        "        else_=-StockTransaction.quantity,\n"
        "    )\n"
    )
    assert _offenses(mutant, "mutant.py")


def test_guard_flags_copied_sign_ternary() -> None:
    """Мутация: удалённая в #317 форма «свой знак» обязана ломать сторожа."""
    mutant = (
        "def f(row):\n"
        "    sign = Decimal(-1) if row.reverses_id is not None else Decimal(1)\n"
        "    return sign * row.quantity\n"
    )
    assert _offenses(mutant, "mutant.py")


def test_legit_active_transaction_filter_not_flagged() -> None:
    """Фильтр активных проводок (stock/api.py) — не арифметика, сторож молчит."""
    legit = (
        "def f(stmt, compensating):\n"
        "    if compensating is True:\n"
        "        stmt = stmt.where(T.reverses_id.is_not(None))\n"
        "    elif compensating is False:\n"
        "        stmt = stmt.where(T.reverses_id.is_(None))\n"
        "    return stmt\n"
    )
    assert _offenses(legit, "stock/api.py") == []


def test_legit_write_side_mirror_not_flagged() -> None:
    """Зеркальная запись/выбор активной проводки — не арифметика."""
    legit = (
        "def f(entry):\n"
        "    return StockTransaction(reverses_id=entry.source_tx_id)\n"
        "\n"
        "def g(txs):\n"
        "    return [t for t in txs if t.reverses_id is None]\n"
    )
    assert _offenses(legit, "reversal/stock_compensator.py") == []
