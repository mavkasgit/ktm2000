"""Проверка самого отчёта по гигиене импортов (`scripts/check-test-imports.py`).

Скрипт — report-only и не падает на находках, поэтому без этих тестов его
логику никто не проверяет: сломанный анализатор молча печатал бы «находок: 0».
Здесь проверяются синтетические файлы в `tmp_path`, а не текущее состояние
репозитория (у репозитория свой отчёт — `npm run test:hygiene`).
"""

from __future__ import annotations

import importlib.util
import pathlib
import types

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CHECKER_PATH = REPO_ROOT / "scripts" / "check-test-imports.py"


def _load_checker() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("check_test_imports", CHECKER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


def _write(tmp_path: pathlib.Path, body: str) -> pathlib.Path:
    path = tmp_path / "sample.py"
    path.write_text(body, encoding="utf-8")
    return path


def test_flags_unused_from_import(tmp_path: pathlib.Path) -> None:
    path = _write(
        tmp_path,
        "from app.models import User\n\n\ndef test_x() -> None:\n    assert True\n",
    )
    assert checker.unused_from_imports(path) == [(1, "User")]


def test_ignores_name_used_in_code(tmp_path: pathlib.Path) -> None:
    path = _write(
        tmp_path,
        "from app.models import User\n\n\ndef test_x() -> None:\n    assert User is not None\n",
    )
    assert checker.unused_from_imports(path) == []


def test_ignores_name_used_only_in_string_annotation(tmp_path: pathlib.Path) -> None:
    """Строковая аннотация — тоже использование: `user: \"User\"`."""
    path = _write(
        tmp_path,
        'from app.models import User\n\n\ndef test_x(user: "User") -> None:\n    assert user\n',
    )
    assert checker.unused_from_imports(path) == []


def test_skips_statement_with_comment(tmp_path: pathlib.Path) -> None:
    """Комментарий в строке импорта — escape hatch для намеренных реэкспортов."""
    path = _write(
        tmp_path,
        "from tests.helpers import make_user  # реэкспорт для потребителей старого пути\n",
    )
    assert checker.unused_from_imports(path) == []


def test_skips_bare_module_import(tmp_path: pathlib.Path) -> None:
    """`import app.models` может быть нужен ради side-effect, а не по имени."""
    path = _write(
        tmp_path,
        "import app.models\n\n\ndef test_x() -> None:\n    assert True\n",
    )
    assert checker.unused_from_imports(path) == []


def test_alias_counts_by_bound_name(tmp_path: pathlib.Path) -> None:
    path = _write(
        tmp_path,
        "from app.models import User as AppUser\n\n\ndef test_x() -> None:\n    assert AppUser is not None\n",
    )
    assert checker.unused_from_imports(path) == []
