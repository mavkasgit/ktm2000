# Factoryflow

Локальная система производственного планирования и контроля.

## Порты (фиксировано)

Каждое окружение получает блок из 10 портов.

- `dev`: `5200-5209`
- `test`: `5210-5219`
- `prod`: `5220-5229`

Текущее назначение:

| Environment | Frontend | Backend | Postgres |
|---|---:|---:|---:|
| dev | 5200 | 5201 | 5202 |
| test | 5210 | 5211 | 5212 |
| prod | 5220 | 5221 | 5222 |

Примечания:

- На текущем этапе в compose поднят `postgres`; порты `frontend/backend` зарезервированы и зафиксированы в `.env.*`.
- Нейминг проекта фиксирован как `factoryflow` (контейнеры, env, package names).

## Быстрый запуск

```bash
npm install
npm --prefix frontend install
npm run db:up
npm run db:wait
npm run db:migrate
```


