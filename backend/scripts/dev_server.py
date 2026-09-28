"""Dev-сервер backend: hot reload, который не роняет остальной dev-стек.

Запуск (cwd = ``backend/``): ``python scripts/dev_server.py``
Используется скриптом ``npm run backend``.

Зачем отдельный скрипт
----------------------
1. **Рестарт не должен убивать соседей по консоли.** uvicorn на Windows
   перезапускает рабочий процесс через
   ``os.kill(pid, signal.CTRL_C_EVENT)``
   (``uvicorn/supervisors/basereload.py:88``). Это
   ``GenerateConsoleCtrlEvent``, а ``pid`` здесь не является id группы
   процессов, поэтому событие получает **вся консоль**: вместе с backend
   умирают FRONTEND и DB из ``npm run dev`` — с кодом 3221225786
   (0xC000013A STATUS_CONTROL_C_EXIT). Vite к этому отношения не имеет, он
   просто collateral. Здесь рабочий процесс убивается точечно:
   ``taskkill /F /T /PID``.
2. **Слушаем только ``backend/app``.** uvicorn всегда добавляет cwd в
   watch-files (``uvicorn/supervisors/watchfilesreload.py:68``), поэтому
   ``--reload-dir app`` сам по себе не спасал: правки ``backend/tests``,
   ``alembic`` и ``scripts`` тоже вызывали рестарт.
3. **Старый код доживает.** Если изменённый файл не компилируется
   (недописанный файл, опечатка) — рестарт пропускается, предыдущий процесс
   продолжает отдавать API.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import uvicorn
from uvicorn._subprocess import get_subprocess
from uvicorn.supervisors import ChangeReload
from uvicorn.supervisors.watchfilesreload import WatchFilesReload

BACKEND_DIR = Path(__file__).resolve().parents[1]
APP_DIR = (BACKEND_DIR / "app").resolve()
APP_IMPORT = "app.main:app"
HOST = "0.0.0.0"
DEFAULT_PORT = 8012
PORT_ENV_VAR = "BACKEND_PORT"


def resolve_port(env: Mapping[str, str] | None = None) -> int:
    """Порт backend'а: ``$BACKEND_PORT``, иначе порт devstack.

    Стенд E2E (#220) поднимает backend на своём порту рядом с работающим
    devstack, поэтому порт не может быть константой. Некорректное значение —
    ошибка, а не тихий откат на 8012: тот порт принадлежит чужому стеку, и
    прогон молча уехал бы в чужой backend.
    """
    source: Mapping[str, str] = os.environ if env is None else env
    raw = (source.get(PORT_ENV_VAR) or "").strip()
    if not raw:
        return DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError as exc:
        raise ValueError(f"{PORT_ENV_VAR}={raw!r} — не число") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"{PORT_ENV_VAR}={raw!r} — вне диапазона 1..65535")
    return port


logger = logging.getLogger("uvicorn.error")


def _syntax_problem(path: Path) -> str | None:
    """Вернуть описание ошибки компиляции или None, если файл в порядке."""
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:  # файл удалён/переименован — не мешает рестарту
        logger.debug("Не читается %s: %s", path, exc)
        return None
    try:
        compile(source, str(path), "exec")
    except SyntaxError as exc:
        return f"{exc.msg} (строка {exc.lineno})"
    except ValueError as exc:  # например, NUL-байт в исходнике
        return str(exc)
    return None


def _should_restart(self: WatchFilesReload) -> list[Path] | None:
    self.pause()

    changes = next(self.watcher)
    if not changes:
        return None

    paths = [Path(change[1]) for change in changes]
    paths = [path for path in paths if path.is_relative_to(APP_DIR) and self.watch_filter(path)]
    if not paths:
        return None

    for path in paths:
        problem = _syntax_problem(path)
        if problem is not None:
            logger.error(
                "Рестарт пропущен: %s не компилируется (%s). Продолжаю работать "
                "на последней валидной версии кода.",
                path.relative_to(BACKEND_DIR),
                problem,
            )
            return None

    return paths


def _restart(self: WatchFilesReload) -> None:
    self.is_restarting = True
    pid = self.process.pid
    if pid is None:  # pragma: no cover — рабочий процесс ещё не стартовал
        return

    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            check=False,
        )
    else:
        self.process.terminate()

    self.process.join()

    self.process = get_subprocess(config=self.config, target=self.target, sockets=self.sockets)
    self.process.start()
    # Сигнала от taskkill не придёт, поэтому сбрасываем флаг сами: иначе
    # следующий Ctrl+C пользователя будет проглочен (basereload.py:42).
    self.is_restarting = False


def main() -> int:
    os.chdir(BACKEND_DIR)
    # uvicorn CLI добавляет cwd в sys.path, мы запускаемся как скрипт — нет.
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    # `.env.dev` перекрывает окружение процесса, иначе устаревшая DATABASE_URL
    # в окружении уводила бы приложение на чужую БД (реloader наследует её в
    # рабочий процесс, поэтому достаточно один раз здесь).
    from app.core.env_file import apply_env_file

    apply_env_file()
    WatchFilesReload.should_restart = _should_restart  # type: ignore[method-assign]
    WatchFilesReload.restart = _restart  # type: ignore[method-assign]

    config = uvicorn.Config(
        APP_IMPORT,
        host=HOST,
        port=resolve_port(),
        reload=True,
        reload_dirs=[str(APP_DIR)],
    )
    server = uvicorn.Server(config)
    # Решение про reloader принимает CLI (uvicorn/main.py), а не Server.run(),
    # поэтому повторяем его здесь — иначе скрипт стартует без hot reload.
    if config.should_reload:
        ChangeReload(config, target=server.run, sockets=[config.bind_socket()]).run()
    else:  # pragma: no cover — при reload=True всегда True
        server.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
