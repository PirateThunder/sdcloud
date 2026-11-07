# backend

Продуктовый backend sdCloud: email/OTP-аутентификация, пользователи, беседы,
модели, версии, поколения и симуляции. Принимает запросы frontend и вызывает
`generation_core` только через внутренний HTTP API.

Версия — **0.6.0**. Общая архитектура и запуск — [корневой README](../README.md).

## Возможности

- Регистрация и вход по одноразовому шестизначному email-коду, без пароля и гостей.
- Access token в памяти frontend и ротируемая refresh-сессия в HttpOnly cookie.
- Изоляция данных по владельцу: чужие беседы, модели и симуляции недоступны.
- CRUD бесед и серверная история сообщений.
- Контекстный чат: ответ, уточнение, создание или редактирование модели.
- Неизменяемые версии canonical `ModelDocument` и экспорт поддерживаемых форматов.
- Идемпотентные generation/simulation jobs с polling, retry и rate limits.
- Отдельные PostgreSQL, Redis, Alembic-миграции, workers и watchdog.

Backend не запускает LLM напрямую и не импортирует предметный код generation_core.

## Структура

```text
app/
  auth/                  Email/OTP, токены и refresh-сессии
  clients/               HTTP-клиент generation_core
  conversations/         Беседы и сообщения
  generations/           Поколения и их Taskiq-задачи
  models/                Модели, версии и exports
  simulations/           Запуски симуляций и их задачи
  users/                 Пользователи
  config.py              BACK_*-настройки
  core_runner.py         Изолированный запуск core CLI
  broker.py              Taskiq broker
  watchdog.py            Watchdog и scheduler
alembic/                  Миграции PostgreSQL
tests/                    API, auth, workers и интеграционные тесты
```

## Запуск

Полный стек запускается из корня репозитория:

```bash
cp .env.example .env
# Настройте LLM и при необходимости SMTP в .env.
docker compose up --build -d

curl http://127.0.0.1:61231/health
curl http://127.0.0.1:61231/ready
curl http://127.0.0.1:61231/docs
```

Compose поднимает `back-db`, `back-redis`, `back-migrate`, `back-api`,
`back-worker`, `back-watchdog` и `back-scheduler`, а также необходимые сервисы
generation_core. Миграции применяются до старта API.

Внутри Docker backend слушает порт `61230`; наружу по умолчанию опубликован
`127.0.0.1:61231`. Значение меняется через `BACK_HOST_PORT` в корневом `.env`.

## Email/OTP и сессии

Первый успешный OTP создаёт пользователя, последующий выполняет вход. В local/test
при `BACK_EMAIL_DEV_CODE=1` код возвращается как `dev_code` в ответе
`POST /api/v1/auth/email/request`; это позволяет разрабатываться без SMTP.

Для реальной почты настройте:

```text
BACK_SMTP_HOST
BACK_SMTP_PORT=465
BACK_SMTP_USER
BACK_SMTP_PASSWORD
BACK_SMTP_FROM
```

`BACK_EMAIL_DEV_CODE=1` запрещён конфигурацией вне local/test. После входа frontend
использует `Authorization: Bearer <access_token>`; refresh token передаётся только
через cookie с path `/api/v1/auth` и ротируется при обновлении сессии.

## HTTP API

Базовый префикс — `/api/v1`. В local/staging/test Swagger UI доступен по `/docs`.

| Область | Основные endpoints |
|---|---|
| Auth | `POST /auth/email/request`, `POST /auth/email/verify`, `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/me` |
| Беседы | `GET/POST /conversations`, `GET/PATCH/DELETE /conversations/{id}` |
| Сообщения | `GET/POST /conversations/{id}/messages` |
| Поколения | `GET /generations`, `GET /generations/{id}`, `POST /generations/{id}/retry` |
| Модели | `GET /models`, `GET/DELETE /models/{id}`, `GET /models/{id}/versions` |
| Версии | `GET /model-versions/{id}`, `GET /models/{id}/versions/{version}/export` |
| Симуляции | `POST/GET /model-versions/{id}/simulations`, `GET /simulations/{id}`, `POST /simulations/{id}/retry` |
| System | `GET /health`, `GET /ready` — без префикса `/api/v1` |

Создание сообщения и симуляции требует заголовок `Idempotency-Key` длиной 8–200
символов. Повтор с тем же ключом и payload возвращает существующую операцию вместо
создания дубликата. Все предметные endpoints требуют аутентификации.

## Конфигурация

Настройки backend используют префикс `BACK_`.

| Переменная | Назначение |
|---|---|
| `BACK_ENV` | `local`, `test`, `staging` или production-like окружение |
| `BACK_DATABASE_URL` | PostgreSQL backend |
| `BACK_REDIS_URL` | Redis backend |
| `BACK_GENERATOR_URL` | Внутренний URL generation_core |
| `BACK_GENERATOR_API_KEY` | Ключ внутреннего generation_core API |
| `BACK_CORS_ORIGINS` | Разрешённые origins через запятую |
| `BACK_TRUST_PROXY_HEADERS` | Доверие proxy-заголовкам; локально `0` |
| `BACK_JWT_SECRET`, `BACK_OTP_SECRET` | Секреты токенов и OTP; заменить вне local/test |
| `BACK_ACCESS_TTL_MINUTES` | TTL access token; `15` |
| `BACK_REFRESH_TTL_DAYS` | TTL refresh-сессии; `30` |
| `BACK_EMAIL_*` | TTL, cooldown и rate limits OTP |
| `BACK_GENERATION_PER_HOUR` | Лимит поколений на пользователя; `30` |
| `BACK_SIMULATION_PER_HOUR` | Лимит симуляций на пользователя; `120` |
| `BACK_GENERATION_TIMEOUT_SECONDS` | Таймаут поколения; `600` |
| `BACK_SIMULATION_TIMEOUT_SECONDS` | Таймаут симуляции; `120` |

Реальные секреты задаются только через `.env`, исключённый из Git. В production-like
окружении dev-секреты по умолчанию отклоняются при старте, а OpenAPI отключается.

## Разработка

Из `backend/`:

```bash
uv sync --frozen
uv run pytest
uv run ruff check .
```

Тесты используют aiosqlite/fakeredis и не требуют запущенный production-стек.
Для ручного применения миграций к настроенной БД:

```bash
uv run alembic upgrade head
```

Для отладки задач из корня:

```bash
docker compose logs -f back-api back-worker back-watchdog back-scheduler
```

Не используйте общую БД или Redis с generation_core: независимость хранилищ и
жизненного цикла сервисов является частью архитектуры.
