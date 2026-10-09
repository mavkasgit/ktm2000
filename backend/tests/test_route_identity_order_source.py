"""Сторож источника: порядок поиска тождества зовут, а не переписывают (#326).

Отдельный синхронный модуль: тест читает файлы, а модуль тестов резолва
целиком асинхронный — блокирующее чтение внутри async-теста запрещено
(ruff ASYNC240).
"""
from __future__ import annotations

import ast
from pathlib import Path

IDENTITY_CALLERS = (
    Path("app") / "services" / "plan_import_service.py",
    Path("app") / "services" / "route_matcher.py",
    Path("app") / "services" / "position_route_batch.py",
    Path("app") / "seeds" / "seeders" / "routes_seeder.py",
)


def test_identity_order_is_called_not_recopied() -> None:
    """Порядок объявлен один раз: вызывающие зовут `find_route_by_identity`.

    Импорт, автоматчик, сид и батч-снимок обязаны ходить в общую функцию.
    Прямой `find_route_by_code`/`find_route_by_name` в них означает, что
    порядок «код → legacy-имя» снова собирают на месте, и он разойдётся.
    """
    app_root = Path(__file__).resolve().parent.parent
    offenders: list[str] = []
    for relative in IDENTITY_CALLERS:
        tree = ast.parse((app_root / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name in {"find_route_by_code", "find_route_by_name"}:
                offenders.append(f"{relative.as_posix()}:{node.lineno}: {name}")
    assert offenders == [], "Порядок тождества собран заново:\n" + "\n".join(offenders)
