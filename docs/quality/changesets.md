# Чек-лист изменения прод-данных: до / после / сравнение / откат

Правило и границы — раздел
[«Изменения прод-данных: версии до/после»](../deployment.md#изменения-прод-данных-версии-допосле)
в [`docs/deployment.md`](../deployment.md); источник правила —
[`docs/stock-import-1c-spec.md`](../stock-import-1c-spec.md) §15. Здесь
исполняемая часть: что снять, куда положить, что приложить к тикету и как
откатиться.

Чек-лист заполняет автор изменения; «ок» или «откатываем» ставит заказчик.
`changeset` здесь — каталог артефактов приёмки (`changesets/<label>`), это не
`plan_change_sets` импорта плана.

## 0. Метка и каталог

1. `<label> = #<тикет>-<slug>` — номер тикета и короткий латинский slug:
   `#461-aliases-1c`, `#462-changesets`. `<label>` одинаков для каталога, имён
   снимков и `meta.json`.
2. Каталог артефактов:
   - dev — `data/backups/changesets/<label>/` (`data/` вне git);
   - prod — `<STORAGE_ROOT>/backups/changesets/<label>/`, то есть на хосте
     `data/storage-prod/backups/changesets/<label>/` (bind-mount хранилища).
3. В shell метку берите в кавычки: `#` иначе начинает комментарий —
   `mkdir "data/backups/changesets/#462-changesets"`.

## 1. До изменения

- [ ] Каталог `<label>` создан, в нём заведён `meta.json` со
      `"status": "before"`.
- [ ] **БД prod:** ручной бэкап в разделе «Бэкапы» → «Создать»
      (`POST /api/backups`, тип `manual`, ротацией не удаляется). Имя архива и
      `sha256` записаны в `meta.json`.
- [ ] **БД dev:** `npm run db:snapshot -- dump "#<тикет>-<slug>-before"`.
      Дамп ляжет в `data/backups/snapshots/<label>-before-<stamp>.sql` (туда
      пишет скрипт); имя файла записано в `meta.json` — `restore` берёт имя
      именно из `snapshots/`.
- [ ] **Каталог** (если меняется): «Справочник сырья» → «Операции» →
      «Экспорт: скачать справочник (Excel)»
      (`GET /api/catalog-import/export-excel`) → `final_catalog_before.xlsx`
      в каталог метки.
- [ ] **Массовый импорт** (если меняются остатки/план): ответ preview сохранён
      как `preview_before.json` (`POST /api/stock/import/remainders/preview`
      либо соответствующая ручка импорта).
- [ ] **Миграция/бэкфилл:** тот же файл миграции и вывод dry-run/предпросмотра
      сохранены рядом (`migration.sql`, `dry-run.txt`).
- [ ] Отпечатки сняты: `sha256` каждого файла «до» (Windows —
      `Get-FileHash <файл> -Algorithm SHA256`, Linux —
      `sha256sum <файл>`), отпечаток БД — имя дампа/архива и его `sha256`.

## 2. Изменение

- [ ] Изменение применено штатным путём: миграция `npm run db:migrate`, импорт
      через UI/ручку, каталог — `apply-excel`.
- [ ] В `meta.json` записаны команды/нажатия и время — дословно, чтобы их можно
      было повторить.
- [ ] При ошибке «после» не снимается: сначала откат по разделу 5, потом
      разбор. Половина пары не прикладывается к тикету.

## 3. После изменения

- [ ] **БД prod:** второй ручной бэкап тем же способом; имя и `sha256` — в
      `meta.json`.
- [ ] **БД dev:** `npm run db:snapshot -- dump "#<тикет>-<slug>-after"`.
- [ ] **Каталог:** повторный экспорт → `final_catalog_after.xlsx`.
- [ ] **Импорт:** id батча истории и ссылка на него записаны в `meta.json`
      (`"batch": { "import": "…", "batch_id": …, "history_url": … }`), preview
      сохранён как `preview_after.json`.
- [ ] **Отчёт изменений** `report.md`: строки `create/update/skip`, поля
      «было → стало», счётчики. Для каталога — diff двух xlsx, для импорта —
      детализация батча.
- [ ] `meta.json` переведён в `"status": "applied"`, заполнен `finished_at`.

## 4. Сравнение и приёмка

- [ ] Контрольная выборка (10–20 строк импорта или артикулов каталога) сверена
      глазами с источником.
- [ ] Счётчики сходятся с ожиданием: число `create/update/skip` объяснимо.
- [ ] Чего не касались — не изменилось: в diff нет посторонних строк.
- [ ] Пути к артефактам и `meta.json` приложены к тикету.
- [ ] Заказчик сравнил пару и вынес вердикт; в `meta.json` —
      `"comparison": { "reviewed_by": …, "verdict": "ok" | "rollback", … }`
      и `"status": "accepted"` либо откат по разделу 5.

## 5. Откат

| Что меняли | Как откатывать |
|---|---|
| Прод-БД (миграция, бэкфилл, массовая правка) | Восстановить ручной бэкап «до»: «Бэкапы» → «Восстановить» (`POST /api/backups/{filename}/restore`). Перед восстановлением снять ещё один бэкап текущего состояния — диагностику не теряем. |
| Dev БД | `npm run db:snapshot -- restore "<label>-before-<stamp>"` (имя без `.sql`, файл ищется в `data/backups/snapshots/`). |
| Импорт остатков | «История импортов остатков» → «Откатить». LIFO **по складу**: откатывается только последний импорт на этом складе, у остальных кнопка заблокирована с причиной. Ручка — `POST /api/stock/import/remainders/batches/{batch_id}/rollback` с `plan_token` из preview-отката. |
| Каталог | Повторно применить `final_catalog_before.xlsx` через `apply-excel` либо точечно поправить артикулы; `final_catalog_after.xlsx` остаётся для сверки. |
| Миграция схемы | Восстановление бэкапа «до» (данные гарантирует бэкап, не `downgrade`); `alembic downgrade` — только когда он детерминированно возвращает и данные. |

- [ ] Откат выполнен по строке своей категории, в `meta.json` —
      `"status": "rolled-back"`, причина и время.
- [ ] После отката снят артефакт фактического состояния и приложен к тикету:
      пара «до/после» не заменяется одним файлом — иначе непонятно, что
      осталось в базе.
- [ ] `db:snapshot` против prod не запускался (скрипт сам откажется при
      `ENV=prod`); на проде — только ручной бэкап приложения.

## Шаблон `meta.json`

Поля обязательные; лишние можно добавлять, переименовывать — нет: по ним
ищут пару и откат.

```json
{
  "label": "#462-changesets",
  "ticket": "https://github.com/mavkasgit/ktm2000/issues/462",
  "author": "<имя>",
  "environment": "prod",
  "started_at": "2026-11-25T10:00:00+03:00",
  "finished_at": "2026-11-25T10:40:00+03:00",
  "status": "before",
  "commands": [
    "POST /api/backups",
    "POST /api/stock/import/remainders/preview",
    "POST /api/stock/import/remainders"
  ],
  "db": {
    "database": "ktm2000_prod",
    "before": {
      "ref": "backup_2026-11-25_07-00-00.zip",
      "sha256": "<hex>"
    },
    "after": {
      "ref": "backup_2026-11-25_07-40-00.zip",
      "sha256": "<hex>"
    }
  },
  "artifacts": {
    "before": [
      { "file": "final_catalog_before.xlsx", "sha256": "<hex>" },
      { "file": "preview_before.json", "sha256": "<hex>" }
    ],
    "after": [
      { "file": "final_catalog_after.xlsx", "sha256": "<hex>" },
      { "file": "preview_after.json", "sha256": "<hex>" },
      { "file": "report.md", "sha256": "<hex>" }
    ]
  },
  "batch": {
    "import": "остатки",
    "batch_id": 123,
    "history_url": "/spg/import-history"
  },
  "rollback": "restore before-бэкапа backup_2026-11-25_07-00-00.zip",
  "comparison": {
    "reviewed_by": "<заказчик>",
    "reviewed_at": "2026-11-25T12:00:00+03:00",
    "verdict": "ok",
    "notes": ""
  }
}
```

`status`: `before` → `applied` → `accepted` | `rolled-back`. Пару «до/после»
не удаляют после приёмки: это аудит изменения, а не временные файлы.
