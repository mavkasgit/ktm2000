"""Report-only проверка гигиены импортов в тестах (без зависимостей, только stdlib).

Зачем: линтера в репозитории нет (B-0003), и мёртвые импорты в тестах копятся
незамеченными — ночная чистка `T-0009` убрала 107 таких имён в 36 файлах.
Скрипт делает эту проверку повторяемой: `npm run test:hygiene`.

Что считает находкой: имя из `from X import Y`, которое в своём файле нигде не
встречается — ни как имя/атрибут, ни внутри строковой аннотации (строки
парсятся как выражения, чтобы `"User"` в аннотации не считалось мёртвым).

Что осознанно НЕ считается:
  * bare `import X` — модуль может импортироваться ради side-effect
    (например `import app.models` регистрирует модели для `Base.metadata`);
  * statement с комментарием внутри — документированный escape hatch для
    намеренных реэкспортов (`tests/stock/test_transfer_stage2.py` отдаёт
    `_release_via_take_to_work` потребителям старого пути импорта).

Режим по умолчанию — report-only: печатает находки и возвращает 0.
`--strict` возвращает 1, если находки есть (для будущего CI, когда решат
включать).

Запуск: python scripts/check-test-imports.py [путь ...]
"""

from __future__ import annotations

import argparse
import ast
import pathlib
import sys

DEFAULT_ROOT = pathlib.Path(__file__).resolve().parents[1] / "backend" / "tests"


def _used_names(tree: ast.AST) -> set[str]:
    used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    used |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        try:
            parsed = ast.parse(node.value, mode="eval")
        except SyntaxError:
            used |= set(node.value.replace("'", " ").replace('"', " ").split())
            continue
        used |= {n.id for n in ast.walk(parsed) if isinstance(n, ast.Name)}
        used |= {n.attr for n in ast.walk(parsed) if isinstance(n, ast.Attribute)}
    return used


def unused_from_imports(path: pathlib.Path) -> list[tuple[int, str]]:
    """[(строка, имя)] — имена из `from … import …`, не используемые в файле."""
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source)
    used = _used_names(tree)

    findings: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module == "__future__":
            continue
        statement = "".join(lines[node.lineno - 1 : node.end_lineno])
        if "#" in statement:  # escape hatch: намеренный реэкспорт
            continue
        for alias in node.names:
            if alias.name == "*":
                continue
            if (alias.asname or alias.name) not in used:
                findings.append((node.lineno, alias.asname or alias.name))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", type=pathlib.Path, default=None)
    parser.add_argument("--strict", action="store_true", help="вернуть 1, если есть находки")
    args = parser.parse_args()

    roots = args.paths or [DEFAULT_ROOT]
    files: list[pathlib.Path] = []
    for root in roots:
        if root.is_dir():
            files.extend(sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts))
        else:
            files.append(root)

    total = 0
    for path in files:
        for lineno, name in unused_from_imports(path):
            print(f"{path}:{lineno}  {name}")
            total += 1

    print(f"\nпроверено файлов: {len(files)}; находок: {total}")
    if total:
        print("Это отчёт, а не падение: реэкспорты помечайте комментарием в строке импорта.")
    return 1 if (args.strict and total) else 0


if __name__ == "__main__":
    sys.exit(main())
