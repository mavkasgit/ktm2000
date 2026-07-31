# Getting Started — KTM-2000

Пошаговая установка с нуля. Архитектура → [project-overview.md](project-overview.md).

## Шаг 1. Зависимости Node

```bash
npm run setup
```

## Шаг 2. Виртуальное окружение Python

```bash
cd backend
python -m venv .venv

# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Linux/macOS:
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

## Шаг 3. Переменные окружения

```bash
cp .env.example .env.dev
```

Порты dev: Postgres `5440`, frontend `5180`, backend `8010`.  
Порты test: Postgres `5441`, frontend `8100`, backend (в контейнере) `8000`.

> Файл `.env` в корне — для MCP-утилит (SSH/SFTP), отдельно от `.env.dev`.

## Шаг 4. Запуск

```bash
npm run dev
```

Автоматически: Postgres в Docker → ожидание готовности → `alembic upgrade head` → backend `:8010` + frontend `:5180`.

- Frontend: [http://localhost:5180](http://localhost:5180)
- Swagger: [http://localhost:8010/docs](http://localhost:8010/docs)

## Шаг 5. Демо-данные (опционально)

```bash
npm run db:seed
```

## Миграции

```bash
npm run db:makemigrate -- "описание изменений"
npm run db:migrate
```

## Troubleshooting

```bash
npm run devkill       # Остановить серверы на 8010 и 5180
npm run devrestart    # Перезапустить dev-окружение
npm run db:down       # Остановить Postgres
npm run db:up         # Поднять Postgres заново
```