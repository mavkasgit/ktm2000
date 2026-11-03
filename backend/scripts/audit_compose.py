"""Аудит compose-файлов (#380): потолок лога, healthcheck, политика restart.

Зачем скрипт, а не пункт в чеклисте. Правило потолка лога живёт в `AGENTS.md`
(«Логи контейнеров»): каждый сервис обязан объявлять `logging: json-file,
max-size 20m, max-file 3`, потому что на этой машине хостового logrotate нет и
без блока json-лог растёт неограниченно. Текст правила никто не исполнял —
«новый сервис в compose — сразу с этим блоком» держалось на внимании
рецензента. Скрипт превращает правило в проверяемое утверждение.

Что проверяется по каждому сервису:

* ``logging`` — драйвер ``json-file`` и опции ``max-size=20m`` / ``max-file=3``
  (ровно тот блок, что требует `AGENTS.md`);
* ``healthcheck`` — объявлен ``test`` (и отдельно показывается, есть ли
  ``interval``/``timeout``/``retries``: без них docker берёт дефолты 30s/30s/3);
* ``restart`` — объявлена политика из ``always`` / ``unless-stopped``
  (``no``/``on-failure`` не считаются: контейнер, упавший навсегда, — это
  простой, а не отказоустойчивость).

Строгость по файлам: ``docker-compose.prod.yml`` — блокирующий (прогон падает
на дыре), dev/test — информационные (их правка пересоздаёт контейнеры при
следующем ``up``, решение по времени — за человеком; список дыр печатается
всегда). ``--strict`` поднимает информационные до блокирующих.

Два режима запуска, и они нарочно разные:

* обычный (по умолчанию) — только разбор YAML, без docker-демона: годится как
  шаг гейта и как быстрый CI-шаг;
* ``--config`` — дополнительно ``docker compose -f <файл> config -q``: ловит
  битый YAML/невалидную схему до деплоя. Требует docker, поэтому в гейт не
  входит, а живёт отдельным CI-шагом.

Исключения — только явным списком ``EXCEPTIONS`` с причиной и датой пересмотра
(правило датированных исключений): молча пропустить сервис скрипт не может.

Запуск из корня репозитория::

    python backend/scripts/audit_compose.py            # prod блокирующий
    python backend/scripts/audit_compose.py --strict   # dev/test тоже блокируют
    python backend/scripts/audit_compose.py --config   # + docker compose config -q
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_DIR = REPO_ROOT / "infra" / "compose"

#: Потолок лога из `AGENTS.md` («Логи контейнеров»).
EXPECTED_LOGGING = {"driver": "json-file", "max-size": "20m", "max-file": "3"}

#: Политика restart, которая означает «контейнер живёт, пока жив хост».
ACCEPTED_RESTART_POLICIES = ("always", "unless-stopped")

#: Файлы, чьи дыры блокируют прогон. dev/test — информационные: их правка
#: пересоздаёт контейнер при следующем ``up`` (для :5441 это окно без живых
#: тестовых прогонов), поэтому решение о моменте — за человеком.
BLOCKING_FILES = ("docker-compose.prod.yml",)

#: Датированные исключения: (файл, сервис, правило) -> причина + дата пересмотра.
EXCEPTIONS: dict[tuple[str, str, str], str] = {
    (
        "docker-compose.prod.yml",
        "cloudflared",
        "healthcheck",
    ): (
        "в образе cloudflare/cloudflared нет шелла и нет curl: CMD-SHELL-проба "
        "упала бы сама, а не по сервису; сам туннель — под профилем `tunnel` и "
        "живёт в network_mode сервис:nginx, а доступность chain'а проверяет "
        "healthcheck nginx (/api/health). Пересмотреть при переходе на always-on "
        "туннель — 2027-05-01."
    ),
}


@dataclass(frozen=True)
class ServiceReport:
    """Одна строка итоговой таблицы."""

    file: str
    service: str
    logging: str
    healthcheck: str
    restart: str
    blocking: bool

    @property
    def gaps(self) -> list[str]:
        """Правила, по которым сервис не проходит (без исключений)."""
        found = []
        for rule, cell in (
            ("logging", self.logging),
            ("healthcheck", self.healthcheck),
            ("restart", self.restart),
        ):
            if cell.startswith("НЕТ"):
                found.append(rule)
        return found

    def as_row(self) -> tuple[str, ...]:
        verdict = "OK" if not self.gaps else ", ".join(self.gaps)
        level = "блокирующий" if self.blocking else "инфо"
        return (self.file, self.service, self.logging, self.healthcheck, self.restart, level, verdict)


def _logging_cell(service: dict[str, Any]) -> str:
    block = service.get("logging")
    if not isinstance(block, dict):
        return "НЕТ logging (лог растёт неограниченно)"
    driver = block.get("driver", "")
    options = block.get("options") or {}
    if not isinstance(options, dict):
        options = {}
    actual = {
        "driver": str(driver),
        "max-size": str(options.get("max-size", "")),
        "max-file": str(options.get("max-file", "")),
    }
    if actual == EXPECTED_LOGGING:
        return "json-file 20m x3"
    diff = ", ".join(
        f"{key}={actual[key] or 'не задан'} (надо {EXPECTED_LOGGING[key]})"
        for key in EXPECTED_LOGGING
        if actual[key] != EXPECTED_LOGGING[key]
    )
    return f"НЕТ logging: {diff}"


def _healthcheck_cell(service: dict[str, Any]) -> str:
    block = service.get("healthcheck")
    if not isinstance(block, dict):
        return "НЕТ healthcheck"
    if not block.get("test"):
        return "НЕТ healthcheck: блок есть, `test` не задан"
    missing = [key for key in ("interval", "timeout", "retries") if key not in block]
    if missing:
        return f"healthcheck без {'/'.join(missing)} (дефолты docker)"
    return (
        f"test + {block.get('interval')} / {block.get('timeout')} "
        f"/ retries {block.get('retries')}"
    )


def _restart_cell(service: dict[str, Any]) -> str:
    policy = service.get("restart")
    if not policy:
        return "НЕТ restart"
    text = str(policy)
    if text not in ACCEPTED_RESTART_POLICIES:
        return f"НЕТ restart: '{text}' (надо {' | '.join(ACCEPTED_RESTART_POLICIES)})"
    return text


def _apply_exception(file_name: str, service_name: str, report: ServiceReport) -> ServiceReport:
    """Заменить дыру на явное исключение (с текстом причины)."""
    values = {
        "logging": report.logging,
        "healthcheck": report.healthcheck,
        "restart": report.restart,
    }
    for rule in ("logging", "healthcheck", "restart"):
        reason = EXCEPTIONS.get((file_name, service_name, rule))
        if reason and values[rule].startswith("НЕТ"):
            values[rule] = f"исключение: {rule} — {reason}"
    return ServiceReport(
        file=report.file,
        service=report.service,
        logging=values["logging"],
        healthcheck=values["healthcheck"],
        restart=values["restart"],
        blocking=report.blocking,
    )


def audit_file(path: Path, *, strict: bool) -> list[ServiceReport]:
    """Разобрать один compose-файл; вернуть строку на сервис."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SystemExit(f"{path.name}: верхний уровень YAML — не отображение")
    services = raw.get("services") or {}
    if not isinstance(services, dict):
        raise SystemExit(f"{path.name}: секция `services` — не отображение")
    blocking = strict or path.name in BLOCKING_FILES
    file_name = path.name
    reports: list[ServiceReport] = []
    for service_name, service in services.items():
        if not isinstance(service, dict):
            raise SystemExit(f"{file_name}: сервис `{service_name}` — не отображение")
        report = ServiceReport(
            file=file_name,
            service=str(service_name),
            logging=_logging_cell(service),
            healthcheck=_healthcheck_cell(service),
            restart=_restart_cell(service),
            blocking=blocking,
        )
        reports.append(_apply_exception(file_name, str(service_name), report))
    if not reports:
        print(f"{file_name}: сервисов нет — проверять нечего")
    return reports


def _render_table(reports: list[ServiceReport]) -> str:
    header = ("файл", "сервис", "logging", "healthcheck", "restart", "уровень", "вердикт")
    rows = [header, *(report.as_row() for report in reports)]
    widths = [max(len(str(row[index])) for row in rows) for index in range(len(header))]
    lines = []
    for index, row in enumerate(rows):
        lines.append(" | ".join(str(cell).ljust(widths[position]) for position, cell in enumerate(row)).rstrip())
        if index == 0:
            lines.append("-+-".join("-" * width for width in widths))
    return "\n".join(lines)


def _referenced_env_files(path: Path) -> list[Path]:
    """`env_file:` из сервисов, развёрнутые относительно каталога файла.

    Нужны только чтобы подложить заглушку под `config -q`: `.env.prod` и
    `.env.test` не в git, и без них compose падает на «env file not found»
    раньше, чем успевает проверить схему.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    found: list[Path] = []
    for service in (raw.get("services") or {}).values():
        if not isinstance(service, dict):
            continue
        entries = service.get("env_file")
        if isinstance(entries, str):
            entries = [entries]
        for entry in entries or []:
            name = entry if isinstance(entry, str) else (entry or {}).get("path", "")
            if name:
                found.append((path.parent / name).resolve())
    return found


def run_compose_config(paths: list[Path]) -> int:
    """`docker compose -f <файл> config -q` по каждому файлу; вернуть код отказа.

    Шаг проверяет *схему* файла, а не содержимое секретов, поэтому отсутствующие
    env-файлы (#367: они не в git) временно заменяются пустой заглушкой и
    удаляются в `finally` — иначе проверка в CI падала бы до валидации.
    """
    if shutil.which("docker") is None:
        print("docker не найден в PATH — `config -q` пропущен (шаг недоступен)")
        return 2
    worst = 0
    for path in paths:
        stubs: list[Path] = []
        for env_path in _referenced_env_files(path):
            if not env_path.is_file():
                env_path.touch()
                stubs.append(env_path)
        try:
            result = subprocess.run(
                ["docker", "compose", "-f", str(path), "config", "-q"],
                capture_output=True,
                text=True,
                check=False,
            )
        finally:
            for stub in stubs:
                try:
                    stub.unlink()
                except OSError:
                    print(f"не удалён заглушенный {stub}", file=sys.stderr)
        label = "ок" if result.returncode == 0 else f"код {result.returncode}"
        note = f" (заглушек env: {len(stubs)})" if stubs else ""
        print(f"config -q {path.name}: {label}{note}")
        if result.returncode != 0:
            print((result.stderr or result.stdout).strip())
            worst = 1
    return worst


def _ensure_utf8_streams() -> None:
    """Не сломать вывод на Windows-кодировке консоли.

    Таблица кириллицей: в cp866/cp1251 часть символов заменяется на «?», и
    отчёт становится нечитаемым (это ровно тот случай, где «проверка молчит»
    выглядит как «всё чисто»). Переключение потока на UTF-8 ничего не стоит
    там, где его нет (перенаправленный в файл поток его не имеет).
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_streams()
    parser = argparse.ArgumentParser(description="Аудит compose: потолок лога, healthcheck, restart")
    parser.add_argument(
        "--file",
        dest="files",
        action="append",
        type=Path,
        help="явный compose-файл (по умолчанию все infra/compose/docker-compose.*.yml)",
    )
    parser.add_argument("--strict", action="store_true", help="дыры dev/test тоже блокируют")
    parser.add_argument(
        "--config",
        action="store_true",
        help="дополнительно docker compose config -q (нужен docker, в гейт не входит)",
    )
    args = parser.parse_args(argv)

    paths = args.files or sorted(COMPOSE_DIR.glob("docker-compose.*.yml"))
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        print("файл не найден: " + ", ".join(missing), file=sys.stderr)
        return 2
    if not paths:
        print(f"в {COMPOSE_DIR} нет compose-файлов", file=sys.stderr)
        return 2

    reports = [report for path in paths for report in audit_file(path, strict=args.strict)]
    print(_render_table(reports))

    blocking_gaps = [report for report in reports if report.blocking and report.gaps]
    info_gaps = [report for report in reports if not report.blocking and report.gaps]
    for report in blocking_gaps:
        print(f"БЛОКИРУЮЩАЯ ДЫРА: {report.file} / {report.service}: {', '.join(report.gaps)}")
    for report in info_gaps:
        print(f"инфо: {report.file} / {report.service}: {', '.join(report.gaps)}")

    config_code = run_compose_config(list(paths)) if args.config else 0
    if blocking_gaps or config_code:
        return 1
    print(f"OK: сервисов {len(reports)}, блокирующих дыр нет, исключений {len(EXCEPTIONS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
