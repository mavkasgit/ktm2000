# Синк-гейт каталога KTM → «Экранчик»

Каталог «Экранчика» (`ekranchik-modern/static/ekranchik.db`, SQLite) и прод-каталог
KTM живут отдельно, но описывают одни и те же профили. Скрипт
[`scripts/sync-ekranchik.py`](../scripts/sync-ekranchik.py) сверяет их и умеет
подтянуть данные Экранчика к текущему проду.

Это **данные**, а не файлы: файловый синк-гейт между KTM и HRMS — отдельный,
[`scripts/verify-sync.mjs`](../scripts/verify-sync.mjs).

## Что синхронизируется

Только два поля у профилей, которые уже есть в Экранчике:

| Поле | Правило |
|---|---|
| `length` | должна совпадать с любой нормальной **или** сырьевой длиной KTM (±1 мм). Если не совпала — ставится основная длина KTM (primary → единственная → минимальная) |
| `quantity_per_hanger` | норма KTM для этой длины (по `hanger_mode`: manual → `manual`, auto → `auto`) |

Имя, заметки и фото **не трогаются**: в Экранчике имя — это код артикула, а в
заметках хранятся связи «Аналог-…». Новые артикулы не добавляются — только
обновляются существующие 191 профиль. Артикулы, которых нет в Экранчике,
печатаются справочно.

## Запуск

```bash
npm run verify:ekranchik        # только проверка, exit 1 при расхождениях
npm run sync:ekranchik          # обновить БД Экранчика (с бэкапом)
```

Напрямую:

```bash
python scripts/sync-ekranchik.py --check
python scripts/sync-ekranchik.py --apply
python scripts/sync-ekranchik.py --check --json
python scripts/sync-ekranchik.py --db ../ekranchik-modern/static/ekranchik.db
```

`--if-enabled` включает проверку только при `KTM_EKRANCHIK_SYNCGATE=1|true|yes|on`
(для будущей автоматики; сейчас ни в `predev`, ни в `gate` не подключено).

## Окружение

| Переменная | По умолчанию |
|---|---|
| `EKRANCHIK_DB` | `../ekranchik-modern/static/ekranchik.db` |
| `KTM_PG_CONTAINER` | `ktm2000-postgres-prod` |
| `KTM_PG_USER` | `ktm2000_user` |
| `KTM_PG_DB` | `ktm2000_prod` |

KTM читается только на чтение через `docker exec … psql`. Запись — в SQLite
Экранчика в одной транзакции; перед ней через `sqlite3.backup()` снимается
бэкап `ekranchik.db.bak-<дата-время>` рядом с БД.

## Почему правило длины такое

В KTM длина разделена на нормальную (`product_lengths.length_mm`) и сырьевую
(`raw_length_mm`), а в Экранчике поле одно. Поэтому «совпало» — это совпадение
с любой из них; так мы не переписываем 2,75 → 2,70 у десятков профилей, где
2,75 — это сырьевая длина. Если же в Экранчике длина, которой у артикула KTM
нет вообще (например, старая 3050), она приводится к основной длине KTM.

Норма (`quantity_per_hanger`) всегда берётся из KTM для выбранной длины —
поэтому в Экранчике появляется то же значение, что показывает карточка KTM.
