"""Данные DisplayCanon (лейблы, роли), авторятся конструкторами моделей (ADR-0004, тикет #26).

Статусы позиций плана, виды выпуска и каталог ролей. Это данные завода
(меняются релизом), не логика сервиса.
"""

from __future__ import annotations

from app.models.user import UserRole
from app.seeds.canon.models import RoleDef

STATUS_LABELS = {
    "draft": "Черновик",
    "invalid": "Ошибка",
    "valid": "Валиден",
    "approved": "Утверждён",
    "released": "Запущен",
    "cancelled": "Отменён",
}

OUTPUT_KIND_LABELS = {
    "ГП": "Готовая продукция",
    "П/ф": "Полуфабрикат",
    "finished_good": "Готовая продукция",
    "semi_finished_shipment": "Полуфабрикат",
}

# Каталог ролей: коды, русские подписи и допустимые разделы навигации
# (путь как ключ из navItems клиента). Контракт спеки #14.
ROLE_DEFS = [
    RoleDef(
        code=UserRole.admin,
        label="Администратор",
        sections=[
            "/",
            "/references",
            "/planning",
            "/execution",
            "/section-tasks",
            "/transfers",
            "/spg",
            "/audit-logs",
            "/settings",
            "/settings/dev",
            "/dev",
        ],
    ),
    RoleDef(
        code=UserRole.planner,
        label="Планировщик",
        sections=[
            "/",
            "/references",
            "/planning",
            "/execution",
            "/section-tasks",
            "/transfers",
            "/spg",
            "/audit-logs",
            "/settings",
            "/dev",
        ],
    ),
    RoleDef(
        code=UserRole.section_manager,
        label="Начальник участка",
        sections=[
            "/",
            "/references",
            "/execution",
            "/section-tasks",
            "/transfers",
            "/spg",
            "/audit-logs",
            "/settings",
            "/dev",
        ],
    ),
    RoleDef(
        code=UserRole.operator,
        label="Оператор",
        sections=[
            "/",
            "/references",
            "/section-tasks",
            "/transfers",
            "/spg",
            "/audit-logs",
            "/settings",
            "/dev",
        ],
    ),
    RoleDef(
        code=UserRole.viewer,
        label="Наблюдатель",
        sections=[
            "/",
            "/references",
            "/section-tasks",
            "/spg",
            "/audit-logs",
            "/settings",
            "/dev",
        ],
    ),
    RoleDef(
        code=UserRole.transporter,
        label="Транспортировщик",
        sections=[
            "/",
            "/references",
            "/section-tasks",
            "/transfers",
            "/spg",
            "/audit-logs",
            "/settings",
            "/dev",
        ],
    ),
]
