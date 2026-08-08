# ADR-0011: Auth-бэкенд — host-адаптеры и presence-гейт синхронизации KTM/HRMS

Дата: 2026-08-08. Статус: принято.

## Контекст

`backend/app/api/routes/auth.py` в KTM-2000 — роутер-монолит (~560 строк): break-glass
login, `/me*`, logout, backchannel-logout живут прямо в роутере. Аналогичная структура
в HRMS (`app/api/auth.py`, ~700 строк). При рефакторинге логика выносится в сервисы:
`break_glass_service`, `profile_service`, расширение `session_service`.

При этом KTM и HRMS делят must-match модули (`unified_profile_service`,
`authentik_client`, `session_core`, `oidc_core`) и имеют разные auth-фичи (KTM:
`/roles`, `/frontchannel-logout`; HRMS: `/sessions*`, DB-аудит break-glass). Дословное
копирование новых сервисов невозможно без потери функциональности одной из систем.

## Решение

Синхронизация auth-бэкенда между KTM и HRMS — через паттерн «core + host-адаптер»
плюс presence-гейт (тот же механизм, что в ADR-0007 для auth-shell):

1. **Общая логика** — в `*_core.py` (must-match, режим `content` в `sync-manifest.json`).
2. **Новые сервисы** (`break_glass_service`, `profile_service`) — host-адаптеры
   одинаковой формы: те же имена и обязанности, содержимое своё (как `session_service`).
3. **Гейт расхождения** — файлы добавляются в `sync-manifest.json` с режимом
   `presence`: обязаны существовать в обоих репозиториях, байты не сверяются.
4. **HRMS ведёт** рефакторинг первым; KTM повторяет зеркально отдельным PR;
   presence-записи добавляются синхронно в оба манифеста, когда зеркальные файлы
   у обоих репозиториев существуют.

## Последствия

- Разные фичи (roles, sessions) — норм и ожидаемо; разная структура auth-роутера —
  исключается presence-гейтом.
- `verify-sync` начнёт падать, если один репозиторий удалит файл — это желаемое поведение.
- Схемы auth (`schemas/auth.py`) — host-specific (поля различаются), в манифест не входят.
