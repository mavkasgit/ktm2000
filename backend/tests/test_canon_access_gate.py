"""Gate: доступ к PlantConfig только из composition root (ADR-0004 §5, ADR-0007).

Запрещён паттерн «произвольный build_plant_config() в середине стека»:
- вызов build_plant_config (в т.ч. через alias `_build`, `_build_cfg`) внутри
  тела любой функции в app/ → fail;
- разрешены только:
  - module-level eager snapshot (`_DEFAULT_X = _build().…`) — carve-out
    ADR-0007 «immutable snapshot»;
  - файлы из allowlist (composition root и реестр канона).

Правило кодирует классификацию ADR-0007:
  fn(x=None): x = _build().x          → запрещено (runtime construction)
  DEFAULT = _build().x на module level → разрешено (snapshot carve-out)
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = BACKEND_ROOT / "app"

# Файлы, где build_plant_config() в теле функции — легитимно (composition root
# FastAPI). Новое «свободное место» требует осознанного изменения теста.
ALLOWLIST = frozenset({
    "app/main.py",
})

# Весь app/seeds/ исключён из сканирования: доступ к canon там by design
# (composition root сидов, ADR-0004 §5-§6: сидеры/CLI строят канон на входе).
SEEDS_TREE = "app/seeds/"


def _resolve_accessor_names(tree: ast.Module) -> set[str]:
    """Имена, связанные с build_plant_config (в т.ч. через alias import)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            # from app.seeds.canon.registry import build_plant_config [as X]
            if module == "app.seeds.canon.registry":
                for alias in node.names:
                    if alias.name == "build_plant_config":
                        names.add(alias.asname or alias.name)
            # from app.seeds.canon import build_plant_config [as X]
            if module == "app.seeds.canon":
                for alias in node.names:
                    if alias.name == "build_plant_config":
                        names.add(alias.asname or alias.name)
            # from app.seeds import build_plant_config [as X]
            if module == "app.seeds":
                for alias in node.names:
                    if alias.name == "build_plant_config":
                        names.add(alias.asname or alias.name)
            continue
        # import app.seeds.canon.registry [as X] — затем X.build_plant_config()
        for alias in node.names:
            if alias.name == "app.seeds.canon.registry":
                names.add(f"{alias.asname or 'registry'}.build_plant_config")
    return names


class _FunctionBodyCallFinder(ast.NodeVisitor):
    """Находит Call build_plant_config внутри тел функций."""

    def __init__(self, accessor_names: set[str]) -> None:
        self.accessor_names = accessor_names
        self.violations: list[tuple[int, str]] = []
        self._in_function = False

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        prev = self._in_function
        self._in_function = True
        self.generic_visit(node)
        self._in_function = prev

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        prev = self._in_function
        self._in_function = True
        self.generic_visit(node)
        self._in_function = prev

    def visit_Lambda(self, node: ast.Lambda) -> None:
        prev = self._in_function
        self._in_function = True
        self.generic_visit(node)
        self._in_function = prev

    def visit_Call(self, node: ast.Call) -> None:
        if self._in_function:
            func_name = self._func_name(node.func)
            if func_name in self.accessor_names:
                self.violations.append((node.lineno, func_name))
        self.generic_visit(node)

    @staticmethod
    def _func_name(func: ast.expr) -> str | None:
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            parts: list[str] = []
            cur: ast.expr = func
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                parts.append(cur.id)
            return ".".join(reversed(parts))
        return None


def _violations_for_file(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    accessor_names = _resolve_accessor_names(tree)
    finder = _FunctionBodyCallFinder(accessor_names)
    finder.visit(tree)
    return finder.violations


def _iter_app_files() -> list[Path]:
    if not APP_ROOT.is_dir():
        return []
    return sorted(
        p
        for p in APP_ROOT.rglob("*.py")
        if p.is_file()
        and not p.relative_to(BACKEND_ROOT).as_posix().startswith(SEEDS_TREE)
    )


def test_no_build_plant_config_inside_function_bodies() -> None:
    """В app/ build_plant_config() не вызывается из тел функций (кроме allowlist)."""
    violations: list[str] = []
    for path in _iter_app_files():
        rel = path.relative_to(BACKEND_ROOT).as_posix()
        if rel in ALLOWLIST:
            continue
        for lineno, name in _violations_for_file(path):
            violations.append(f"{rel}:{lineno}: {name}()")
    assert not violations, (
        "ADR-0004 §5 / ADR-0007: build_plant_config() запрещён в теле функции "
        "вне composition root. Вынеси резолв в composition root и передай "
        "данные параметром (или оформи module-level snapshot). Нарушения:\n"
        + "\n".join(violations)
    )


def test_accessor_re_exported_from_canon_package() -> None:
    """app.seeds.__init__ остаётся единой точкой реэкспорта accessor'а."""
    init = APP_ROOT / "seeds" / "__init__.py"
    tree = ast.parse(init.read_text(encoding="utf-8"), filename=str(init))
    exported = {
        a.asname or a.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for a in node.names
    }
    assert "build_plant_config" in exported
