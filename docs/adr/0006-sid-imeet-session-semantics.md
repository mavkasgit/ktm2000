# ADR-0006: sid — только session semantics

Дата: 2026-08-08. Статус: принято.

## Контекст

В KTM-2000 два параллельных эмиттера JWT: низкоуровневый shim
`app/core/security.create_access_token` (session_id опционален) и
`app/services/session_service.issue_app_token` (всегда создаёт сессию и
кладёт её id в claim `sid`). Гейт аутентификации (`app/api/deps.py`,
strict mode) требовал `sid` и активную строку в `user_sessions`, но
инвариант «JWT ⟹ активная сессия» держался только на порядке проверок:
ветка break glass была размещена раньше проверки `sid`, потому что её токен
нёс выдуманный `sid = uuid4()`, не существующий в `user_sessions`
(реальная сессия для break glass невозможна: `UserSession.user_id` —
NOT NULL FK на `users.id`, а у break glass нет пользователя). Перестановка
двух условий молча ломала прод.

Плюс claim `sid` имел два референта: указатель на сессию и корреляционный
UUID audit-событий break glass (вход/выход), что делало инвариант
несформулируемым без оговорок.

## Решение

1. **`sid` — только session semantics**: `sid` всегда ссылается на
   активную сессию пользователя из `sub`. Гейт проверяет не только
   активность сессии, но и `session.user_id == user.id` (cross-check).
   Инвариант без оговорок: *если JWT содержит `sid`, то `sid` — ссылка на
   соответствующую активную сессию пользователя из `sub`.*
2. **Break glass не несёт `sid`**: правомочность определяется флагом
   `is_break_glass`, сессия не создаётся и не проверяется. Корреляция
   audit-событий входа/выхода — через отдельный непрозрачный claim
   `corr_id` (фигурирует в log-строках `_record_break_glass_event`;
   записи в `user_login_events` для break glass не создаются вовсе).
3. **Единственный минтер break glass — `create_break_glass_token`**
   (в `app/core/security.py`): инкапсулирует форму claims
   (`is_break_glass` + `corr_id`), структурно не может добавить `sid`.
   Сигнатура `security.create_access_token` не меняется (`session_id`
   остаётся опциональным для dev/tests).
4. **Гейт классифицирует kind токена** (dev / break glass / regular):
   dev-ветка — отдельный escape hatch (`DEV_BYPASS_AUTH`); break glass —
   без обращения к БД сессий; regular — единственная точка валидации
   `sid` (`_require_sid_active`), недостижимая из break-glass-пути.
5. **Гибрид `is_break_glass` + `sid` → 401**: аномалия не маскируется.
   Правило действует в strict-гейте; dev-ветка (`DEV_BYPASS_AUTH`) —
   доверенный escape hatch и гибрид там не разбирает (там sid опционален
   и magic `admin` допустим по определению).

## Отвергнутые альтернативы

- **Двухсмысленный `sid`** (оставить `sid` и как корреляционный id):
  инвариант остаётся несформулируемым, «ложь» в токене сохраняется.
- **Реальные сессии для break glass**: невозможны без миграции
  `user_sessions.user_id` на nullable + строки-призраки.
- **Терпимость к гибриду** (трактовать `is_break_glass`+`sid` как break
  glass): прячет аномалию вместо диагностики.
- **Типизированная классификация TokenKind**: избыточная церемония
  ради одного бита флага.

## Последствия

- Схема claims break glass меняется: появляется `corr_id`, исчезает `sid`.
  Frontend не затронут (потребляет только `/auth/me` профиль,
  не сырые claims).
- `_record_break_glass_event` логирует `corr_id` вместо `sid`; break glass
  не пишет строки в `user_login_events`.
- `app/services/session_core.py` (must-match с HRMS) не изменяется;
  изменения — только в host-слое (`auth.py`, `deps.py`, shim `security.py`,
  тесты).
- Тесты фиксируют оба конца инварианта: минтер break glass без `sid`,
  regular-токен с фиктивным `sid` → 401, гибрид → 401, cross-check
  `sub`↔`sid`.
