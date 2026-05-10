# KTM-2000

Локальная система производственного планирования и контроля.

## Порты (фиксировано)

Каждое окружение получает блок из 10 портов.

- `dev`: `5200-5209`
- `test`: `5210-5219`
- `prod`: `5220-5229`

Текущее назначение:

| Environment | Frontend | Backend | Postgres |
|---|---:|---:|---:|
| dev | 3000 (local) | 8000 (local) | 5202 (docker) |
| test | 5210 | 5211 | 5212 |
| prod | 5220 | 5221 | 5222 |

Примечания:

- Для `dev` через `npm run dev` в Docker поднимается только `postgres`; `backend` и `frontend` запускаются локально.
- Нейминг проекта фиксирован как `ktm2000` (контейнеры, env, package names).

## Быстрый запуск

```bash
npm install
npm --prefix frontend install
npm run dev
```

`npm run dev` выполняет:
- `docker compose ... up -d postgres`
- ожидание healthcheck БД
- `alembic upgrade head`
- локальный запуск backend (`:8000`) и frontend (`:3000`)

## Тесты (отдельная БД)

Тесты запускаются только против отдельной БД `ktm2000_test` на `localhost:5212`, чтобы не обнулять dev-данные.

```bash
npm run test:pytest
```
