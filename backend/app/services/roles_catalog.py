from app.models.user import UserRole


# Единственная точка правды на сервере: коды ролей, русские подписи
# и допустимые разделы навигации (путь как ключ из navItems клиента).
ROLES_CATALOG: list[dict] = [
    {
        "code": UserRole.admin,
        "label": "Администратор",
        "sections": [
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
    },
    {
        "code": UserRole.planner,
        "label": "Планировщик",
        "sections": [
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
    },
    {
        "code": UserRole.section_manager,
        "label": "Начальник участка",
        "sections": [
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
    },
    {
        "code": UserRole.operator,
        "label": "Оператор",
        "sections": [
            "/",
            "/references",
            "/section-tasks",
            "/transfers",
            "/spg",
            "/audit-logs",
            "/settings",
            "/dev",
        ],
    },
    {
        "code": UserRole.viewer,
        "label": "Наблюдатель",
        "sections": [
            "/",
            "/references",
            "/section-tasks",
            "/spg",
            "/audit-logs",
            "/settings",
            "/dev",
        ],
    },
    {
        "code": UserRole.transporter,
        "label": "Транспортировщик",
        "sections": [
            "/",
            "/references",
            "/section-tasks",
            "/transfers",
            "/spg",
            "/audit-logs",
            "/settings",
            "/dev",
        ],
    },
]


def roles_catalog() -> list[dict]:
    """Справочник ролей: коды, подписи и допустимые разделы навигации."""
    return [dict(entry) for entry in ROLES_CATALOG]
