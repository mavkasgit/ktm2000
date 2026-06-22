#!/bin/bash

# Папка для хранения бэкапов на сервере
BACKUP_DIR="${BACKUP_DIR:-/home/ubuntu/backups/archive}"
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
TEMP_DIR="/tmp/backup_ktm2000_$TIMESTAMP"

# Создаем временную директорию
mkdir -p "$TEMP_DIR"
mkdir -p "$BACKUP_DIR"

echo "=== Старт бэкапа KTM-2000: $TIMESTAMP ==="

# Находим корневую папку проекта
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Подгружаем переменные из .env
if [ -f "$PROJECT_ROOT/.env" ]; then
    source "$PROJECT_ROOT/.env"
fi

DB_USER=${POSTGRES_USER:-ktm2000_user}
DB_NAME=${POSTGRES_DB:-ktm2000_prod}
DB_PASS=${POSTGRES_PASSWORD:-ktm2000_prod_pass}
CONTAINER_NAME=${POSTGRES_CONTAINER_NAME:-ktm2000-postgres-prod}
STORAGE_DIR="$PROJECT_ROOT/storage"

echo "Резервное копирование базы данных из контейнера $CONTAINER_NAME..."
docker exec -e PGPASSWORD="$DB_PASS" "$CONTAINER_NAME" pg_dump -U "$DB_USER" "$DB_NAME" > "$TEMP_DIR/ktm2000_db.sql"

# Копирование загруженных файлов (медиа)
if [ -d "$STORAGE_DIR" ]; then
    echo "Копирование папки с файлами из $STORAGE_DIR..."
    cp -r "$STORAGE_DIR" "$TEMP_DIR/storage"
else
    echo "Предупреждение: папка с файлами $STORAGE_DIR не найдена!"
fi

# Архивирование
echo "Создание архива..."
tar -czf "$BACKUP_DIR/backup_ktm2000_$TIMESTAMP.tar.gz" -C "$TEMP_DIR" .

# Очистка временных файлов
rm -rf "$TEMP_DIR"

# Ротация бэкапов (удаляем архивы старше 14 дней)
echo "Очистка старых бэкапов (старше 14 дней)..."
find "$BACKUP_DIR" -type f -name "backup_ktm2000_*.tar.gz" -mtime +14 -delete

echo "=== Бэкап KTM-2000 успешно завершен! ==="
