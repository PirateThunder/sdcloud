# PRD: переписывание sdCloud на модульно-микросервисную архитектуру

**Статус:** generation_core 0.2.0, backend и frontend реализованы и проверены; production release не выполнен; полный benchmark core 26×3 не запускался
**Порядок реализации:** `generation_core → backend → frontend`  
**Источник функциональности:** `../sdcloud_old/code`  
**Архитектурные ориентиры:** `../piratepress`, `../piratepitch`

## 1. Контекст

sdCloud — AI-ассистент, который превращает текстовое описание системы в системно-динамическую модель: переменные, уравнения, CLD, SFD, Python/Vensim-код и результаты симуляции.

Текущая реализация объединяет LLM, генерацию, симуляцию, пользователей, чаты и HTTP API внутри `backend`. Целевая версия должна повторить модульную границу PiratePress/PiratePitch:

- независимый генератор с CLI, HTTP API, очередью и воркером;
- продуктовый backend, который обращается к генератору только по HTTP;
- frontend, который обращается только к продуктовому backend;
- отдельные данные, миграции, очереди, конфигурация и жизненный цикл развёртывания каждого модуля.

Каталог `sdcloud` на момент составления документа пуст, поэтому работа рассматривается как создание нового монорепозитория с переносом проверенной доменной логики из `sdcloud_old/code`, а не как постепенный рефакторинг существующих файлов на месте.

## 2. Цели

1. Сохранить пользовательские возможности sdCloud и специфичный scientific stack: PySD, SciPy, NetworkX, NumPy, Pandas.
2. Выделить генерацию и симуляцию в автономный `generation_core`, пригодный для запуска через CLI и HTTP.
3. Перенести архитектурные практики reference-проектов: by-domain backend, Taskiq + Redis, PostgreSQL + Alembic, идемпотентные задачи, изолированные workdir, Next.js + FSD.
4. Устранить выполнение произвольного Python-кода, полученного от браузера.
5. Сделать сбой генерации или симуляции изолированным: он не должен ронять API или повреждать чужие задачи.
6. Обеспечить независимую проверку каждого этапа до перехода к следующему.

## 3. Не входит в объём первой версии

- Редактор CLD/SFD и ручное редактирование уравнений.
- Multi-agent/self-reflection контур, fine-tuning и обучение на пользовательских правках.
- Telegram/VK-боты, Mini Apps, биллинг, публичный API для сторонних клиентов.
- WebSocket/SSE-стриминг; в первой версии используется polling.
- Совместимость старых HTTP-контрактов «один в один»: backend и frontend выпускаются согласованно.
- Автоматическая симуляция после каждой генерации; симуляция остаётся отдельным действием пользователя.
- Одновременный перенос функциональности из будущих планов `kimi-agent-plans.md`.

## 4. Пользовательский объём и паритет

### 4.1 Доступ

- Гостевой режим, guest credentials, guest jobs и их TTL отсутствуют.
- Единый вход и регистрация выполняются через email и одноразовый шестизначный код; пароль, username, OAuth и Mini Apps не используются.
- Первый успешный OTP создаёт пользователя с подтверждённым email; последующий OTP выполняет вход в существующий аккаунт.
- Все чаты, модели, симуляции и exports требуют аутентификации и доступны только владельцу.
- Access token хранится в памяти frontend; отзываемая refresh-сессия — в HttpOnly cookie.

### 4.2 Пользовательские возможности

- Создание, просмотр, переименование и удаление бесед.
- Серверная история сообщений, версий моделей и симуляций.
- Контекстная беседа: ответы на вопросы и уточнения без генерации модели; явные запросы на изменение создают новую версию из `base_model + change_request`.
- Отправка описания системы и получение модели с понятными стадиями и ошибками.
- Просмотр переменных, уравнений, assumptions, warnings, CLD, SFD и кода.
- Сохранение каждой успешной генерации или редакции как неизменяемой версии canonical ModelDocument; текстовые ответы версий не создают.
- Запуск симуляции конкретной версии с параметрами времени, integration method и custom parameters.
- Просмотр графика и истории запусков; экспорт Python/Vensim/XMILE при поддержке конкретной моделью.

### 4.3 Доменный результат генерации

Версионированный документ модели должен содержать:

- `schema_version`;
- `variables`: stock, flow, auxiliary, constant;
- `equations`;
- `cld_data`: nodes, edges, validation, feedback loops;
- `sfd_data`: nodes, edges, validation;
- `python_code`;
- `vensim_code`;
- `assistant_text`, если сформирован LLM;
- предупреждения, журнал стадий и технические метаданные прогона.

Пустой или неисполняемый результат нельзя возвращать как `done`, даже если отдельные LLM-стадии завершились без исключения.

## 5. Целевая архитектура

```text
Browser
   │ same-origin /api/*
   ▼
frontend / Next.js
   │ rewrites, BACKEND_URL
   ▼
backend back-api ─────► back-db
   │ kick                  │
   ▼                       │
back-redis ◄──────── back-worker
                           │ HTTP + X-API-Key + Idempotency-Key
                           ▼
                    generator gen-api ─────► gen-db
                           │ kick              │
                           ▼                   │
                    gen-redis ◄──────────── gen-worker
                                               │ subprocess
                                               ▼
                                    generate.py / simulate.py
                                               │
                                    work_api/<job_id>/ артефакты
```

### 5.1 Жёсткие границы

- `frontend` не знает адрес `generation_core` и не вызывает его.
- `backend` не импортирует Python-модули генератора и не читает его БД.
- `generation_core` не знает о пользователях, JWT, беседах и продуктах.
- Внутренний `gen-api` доступен только в приватной Docker-сети и защищён `X-API-Key`.
- У модулей разные БД, схемы миграций и Redis logical DB/очереди. Они могут физически находиться на shared PostgreSQL/Redis, но не имеют доступа к данным друг друга.
- Все длительные операции выполняются в воркерах; HTTP API только валидирует, регистрирует и ставит задачу.

### 5.2 Структура монорепозитория

```text
sdcloud/
├── generation_core/
│   ├── pipeline/
│   │   ├── schemas.py
│   │   ├── generation.py
│   │   ├── llm/
│   │   ├── graphs/
│   │   ├── simulation/
│   │   └── export/
│   ├── prompts/
│   ├── service/
│   │   ├── models/
│   │   ├── simulations/
│   │   ├── jobs/
│   │   └── system/
│   ├── alembic/
│   ├── tests/
│   ├── generate.py
│   ├── simulate.py
│   ├── pyproject.toml
│   └── Dockerfile
├── backend/
│   ├── app/
│   │   ├── auth/
│   │   ├── users/
│   │   ├── conversations/
│   │   ├── generations/
│   │   ├── models/
│   │   ├── simulations/
│   │   ├── clients/generator.py
│   │   ├── database.py
│   │   ├── broker.py
│   │   └── main.py
│   ├── alembic/
│   ├── tests/
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/
│   ├── src/app/                 # тонкий App Router
│   ├── src/fsd/{app,pages,widgets,features,entities,shared}/
│   ├── e2e/
│   └── package.json
├── docker-compose.yml
├── docker-compose.prod.yml
├── Caddyfile
└── PRD.md
```

## 6. Технологический стек

| Слой | Общий стек по reference-проектам | Специфика sdCloud |
|---|---|---|
| Python | Python 3.13, uv, Pydantic 2, pydantic-settings, Ruff, pytest | PySD, SciPy, NetworkX, NumPy, Pandas |
| HTTP | FastAPI, Uvicorn, httpx | OpenRouter/OpenAI-compatible LLM client |
| Данные | PostgreSQL 17, SQLAlchemy 2 async, asyncpg, Alembic | JSONB-документы моделей и временных рядов |
| Очереди | Redis 7, Taskiq, taskiq-redis | Отдельные generation/simulation job kinds |
| Frontend | Bun, Next.js 16 App Router, React 19, TypeScript, Tailwind 4, Base UI/shadcn pattern, Biome | `@xyflow/react`, Recharts, react-markdown, remark-gfm |
| Состояние | TanStack Query, Zustand, ky, Zod | Session и drafts; серверная история |
| Тесты UI | Playwright против production build | Сохранить Vitest/Testing Library для компонентных тестов |
| Инфраструктура | Docker Compose, отдельные api/worker/migrate процессы, приватная внутренняя сеть | Изолированный subprocess для вычислений |

**Compatibility gate:** до переноса кода проверить PySD/SciPy/NumPy/Pandas на Python 3.13 и зафиксировать версии в `uv.lock`. Если закреплённый совместимый scientific stack требует Python 3.12, только `generation_core` может временно остаться на 3.12; HTTP-контракт от этого не меняется. Такое отступление фиксируется отдельным решением, а не обнаруживается в конце миграции.

Access JWT реализуется через PyJWT. Refresh — opaque token с хешем в серверной `AuthSession`, атомарной rotation и отзывом. OTP хранится в Redis как HMAC-хеш. Password hashes не переносятся: доступ к старому аккаунту подтверждается OTP на его email.

## 7. Контракты модулей

### 7.1 CLI generation_core

```bash
uv run python generate.py --input request.json --workdir work/<run_id>
uv run python simulate.py --model model.json --params params.json --workdir work/<run_id>
```

Требования:

- вход и выход — JSON по Pydantic-схемам;
- ненулевой exit code при ошибке;
- `stdout/stderr` доступны для `job.log`;
- каждый запуск использует отдельный workdir;
- повторный запуск одного deterministic fixture даёт эквивалентный модельный документ;
- LLM вызывается только на стадиях, которым он необходим; Python-код генерируется детерминированно из проверенных уравнений.

Артефакты генерации: `model.json`, `model.py`, `model.mdl`, `manifest.json`, `job.log`.  
Артефакты симуляции: `simulation.json`, `manifest.json`, `job.log`.

### 7.2 Внутренний HTTP API generation_core

Базовый префикс: `/api/v1`; все ручки, кроме health, требуют `X-API-Key`.

| Метод | Назначение |
|---|---|
| `POST /models` | Низкоуровневый generation job из описания и ограниченного контекста |
| `POST /chat` | Контекстный ответ, уточнение или новая версия из текущего `base_model` и запроса на изменение; CLI `chat.py` использует тот же pipeline |
| `POST /simulations` | Создать simulation job из canonical model document и параметров |
| `GET /jobs/{job_id}` | Статус, стадия, ошибка, manifest, список артефактов |
| `GET /jobs/{job_id}/result` | `response.json`, `model.json` или `simulation.json` после `done` |
| `GET /jobs/{job_id}/log?tail=N` | Хвост журнала |
| `GET /jobs/{job_id}/files/{path}` | Только whitelisted артефакт |
| `POST /jobs/{job_id}/retry` | Ручной повтор только после `error` |
| `GET /health`, `GET /ready` | Liveness/readiness |

Статусы core: `pending → running → done | error`.

`POST /models`, `POST /chat` и `POST /simulations` принимают `Idempotency-Key`. Повтор свежего ключа возвращает исходную задачу и не вызывает LLM повторно. Конфигурация модели и провайдера задаётся серверным env, а не произвольными параметрами браузера.

`SimulationRequest` не принимает сырой Python от внешнего клиента. Backend передаёт сохранённый canonical model document ранее успешной генерации. Перед запуском generator повторно проверяет его схему и AST уравнений; browser не имеет доступа к этому внутреннему endpoint.

### 7.3 Публичный backend API

Базовый префикс: `/api/v1`.

| Область | Методы |
|---|---|
| Auth | `POST /auth/email/request`, `POST /auth/email/verify`, `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/me` |
| Conversations | CRUD бесед и `GET /conversations/{id}/messages` |
| Generations | `POST /conversations/{id}/messages`, `GET /generations/{id}`, `POST /generations/{id}/retry` |
| Models | `GET /models`, `GET /models/{id}`, `DELETE /models/{id}`, `GET /models/{id}/versions/{version}/export?format=python|vensim|xmile` |
| Simulations | `POST /model-versions/{id}/simulations`, `GET /model-versions/{id}/simulations`, `GET /simulations/{id}`, `POST /simulations/{id}/retry` |
| System | `GET /health`, `GET /ready` |

Отправка сообщения возвращает `202 Accepted`, идентификаторы сообщений и `generation_id`. Публичные статусы: `queued → submitted → running → done | error`, плюс отдельное поле `stage`.

Backend worker:

1. Атомарно создаёт/получает generation.
2. Отправляет задачу в core с `Idempotency-Key = generation.id`.
3. Сохраняет `generator_job_id`.
4. Опрашивает core до терминального статуса.
5. Скачивает и валидирует результат.
6. Сохраняет snapshot модели/симуляции в backend БД.
7. Обновляет assistant message и публичный статус.

После сохранения snapshot чтение модели и экспорт не зависят от доступности core.

### 7.4 Email/OTP и сессии

- OTP: 6 цифр, TTL 10 минут, cooldown 60 секунд, максимум 5 попыток и лимиты по email/IP.
- Хранится только HMAC-хеш кода в Redis; проверка и погашение атомарны, повторное использование запрещено.
- Ответ на request не раскрывает наличие аккаунта. Код не попадает в production-ответы и обычные логи.
- Отдельной регистрации нет: первый verify делает find-or-create по нормализованному email и заполняет `email_verified_at`.
- Почтовая отправка выделена в `EmailSender`; development provider доступен только в явно локальном окружении.
- Access JWT живёт 15 минут. Opaque refresh хранится в HttpOnly Secure SameSite=Lax cookie, его HMAC-хеш — в `AuthSession` в PostgreSQL.
- Refresh rotation атомарна; старый токен отзывается, повторное его использование отзывает скомпрометированную сессию. Logout отзывает серверную сессию.

## 8. Данные backend

Основные сущности:

- `User`: UUID, уникальный normalized email, display name, email verification, активность, timestamps; без username/password.
- `AuthSession`: владелец, refresh hash, expiry, rotation/revocation, last used, optional device metadata.
- `Conversation`: владелец, название, last_message_at, timestamps.
- `Message`: беседа, role, markdown content, status, timestamps; произвольный `model_metadata` не является источником модели.
- `Generation`: владелец, conversation/user/assistant messages, request snapshot, idempotency key, приватный generator job id, status/stage, error, usage и timestamps.
- `Model`: логическая модель в библиотеке пользователя с текущей версией.
- `ModelVersion`: неизменяемый canonical ModelDocument 2.0, generation, version number, model hash, validation и artifacts metadata. Статус генерации в версии не дублируется.
- `Simulation`: владелец, `model_version_id`, generator job id, params, status, result snapshot, фактические engine/method, fallback reason, error, timestamps.

Требования:

- UUID и timezone-aware UTC timestamps;
- FK и indexes для всех owner lookups, включая денормализованный `owner_id` дочерних ресурсов;
- unique constraint для idempotency scope и `(model_id, version)`;
- каскадное удаление только внутри ресурсов владельца;
- Alembic migrations без прямого доступа к `gen-db`;
- JSONB валидируется Pydantic перед сохранением и при чтении контракта;
- симуляции и exports всегда ссылаются на неизменяемую версию, а не на перезаписываемый текущий документ.

## 9. Нефункциональные требования

### 9.1 Надёжность

- Не использовать `asyncio.create_task` для платных/длительных операций.
- Retry HTTP только для transport/временных ошибок и только с idempotency; не повторять автоматически завершившуюся ошибкой LLM-генерацию.
- Таймаут subprocess, ограничение параллелизма, отдельный workdir и атомарная запись артефактов.
- Watchdog отмечает зависшие queued/running jobs ошибкой.
- После рестарта воркер не создаёт дубль генерации с тем же idempotency key.
- PySD — основной engine; SciPy — fallback. В результате сохраняются `engine` и `fallback_reason`; при ошибке обоих возвращается sanitised summary обеих причин.

Предлагаемые начальные настройки: polling 2 секунды, generation timeout 10 минут, simulation timeout 60 секунд, core concurrency 1–2. Все значения задаются env и уточняются после нагрузочной проверки.

### 9.2 Безопасность выполнения моделей

Возможность передать произвольный `python_code` в simulation не переносится.

- Принимаются только canonical model documents, прошедшие генерацию и schema validation.
- Уравнения проходят AST whitelist: разрешённые операторы, числовые константы, переменные и ограниченный набор функций; imports, attribute access, lambdas и произвольные calls запрещены.
- Python формируется только детерминированным генератором после этой проверки.
- Вычисления выполняются в отдельном subprocess под непривилегированным пользователем, с ограничениями времени, памяти, CPU и размера результата; workdir очищается.
- Валидируются `time_end > time_start`, `time_step > 0`, максимальное число точек и конечность всех значений.
- Path traversal исключается whitelist артефактов и проверкой resolved path.

### 9.3 Auth и API

- Access token — в памяти frontend; refresh — HttpOnly Secure SameSite cookie, single-flight refresh на клиенте.
- Единственный способ входа — email/OTP; username/password, VK/Telegram и guest credentials отсутствуют.
- Все model/generation/simulation queries проверяют владельца; чужой ресурс возвращает 404.
- Rate limits на OTP request/verify, generation, simulation и retry.
- Refresh/logout с cookie защищаются SameSite, allowlist CORS и проверкой Origin; refresh rotation выполняется атомарно.
- Ошибки пользователя не содержат API keys, OTP, полные prompts, stack traces или внутренние пути.

### 9.4 Наблюдаемость

Структурированные логи с `request_id`, `generation_id`/`simulation_id`, `generator_job_id`, stage, duration, engine и LLM model/provider. В manifest сохраняются durations, usage/cost, если доступны, версии схемы и generator. Health не зависит от внешних систем; ready проверяет необходимые зависимости.

## 10. План реализации

Каждый этап завершается отдельным работающим deliverable. Следующий этап не начинается, пока не выполнен Definition of Done предыдущего.

### Этап 0. Baseline и контракты

1. Создать каркас монорепозитория, uv/bun конфигурации, Docker Compose и правила качества.
2. Составить матрицу переноса старых файлов и удалить зависимости переносимой логики от `app.*`, FastAPI и ORM.
3. Зафиксировать 5–10 характерных примеров: exponential growth, predator–prey, SIR, inventory и ошибочные LLM outputs.
4. Записать characterization fixtures для старых postprocess, graph builders, Python/Vensim generators и SciPy runner. Не снимать snapshots живого LLM как обязательный точный результат.
5. Проверить scientific stack на Python 3.13, зафиксировать lockfiles.
6. Выпустить JSON Schema/OpenAPI черновик canonical model, job status и ошибок.

**DoD:** fixtures запускаются против старой логики; контракты согласованы; совместимость Python подтверждена; известные расхождения старой SPEC и фактического кода записаны.

### Этап 1. generation_core

#### 1.1 Чистый доменный движок

- Перенести OpenRouter client, prompts, model postprocess, CLD/SFD builders, graph validator, deterministic Python generator и Vensim exporter.
- Перенести PySDRunner и SciPy fallback, удалив imports backend exceptions/config/database.
- Ввести единые Pydantic-схемы и доменные исключения.
- Разбить pipeline на явные стадии: `variables → cld → equations → postprocess → consistency → sfd → python → vensim`.
- Добавить `generate.py` и `simulate.py`, файловые артефакты и manifest.
- Добавить AST whitelist и отказ от пустого `done`.

#### 1.2 Сервисная оболочка

- Реализовать by-domain FastAPI service, `Job(kind=generate|simulate)`, собственные PostgreSQL/Alembic.
- Добавить Redis/Taskiq worker, subprocess runner, отдельные workdir, concurrency, timeout и логирование.
- Реализовать idempotency, retry после error, whitelisted files, health/ready.
- Настроить `gen-api`, `gen-worker`, `gen-migrate`, `gen-db`, `gen-redis` в Compose.

#### 1.3 Проверки generation_core

- Unit: schemas, prompts parsing, malformed JSON, postprocess, graph validation, AST restrictions, Python/Vensim generation.
- Numerical: известные analytic models и сравнение PySD/SciPy с допусками; не сравнивать floating point побайтово.
- CLI integration: полный generate и simulate без backend, LLM mocked на границе client.
- API integration: 202 → polling → result/files; idempotent replay; retry; timeout; worker restart; две параллельные задачи.
- Security: client-supplied Python отклонён, malicious equation отклонён, path traversal отклонён.

**DoD:** `uv run pytest` и `uv run ruff check .` зелёные; CLI работает; через containerized gen-api реальный пример проходит generation → simulation; ошибка subprocess не роняет API; повтор idempotency key не вызывает повторную генерацию.

### Этап 1.5. Scientific hardening и SD interoperability

Базовый `generation_core` доработан по отдельному [PRD Generation Core 2.0](generation_core/PRD.md): canonical ModelDocument 2.0, корректные численные методы и временная сетка, полные временные ряды, units/topology validation, детерминированные CLD/SFD, базовый SD-диалект с lookups/delays/events, Vensim/XMILE import и Python/Vensim/XMILE/CSV export.

Backend gate из `generation_core/PRD.md` выполнен: backend использует контракт 2.0 и не зависит от документов 1.0. LLM quality improvements, scenarios, sensitivity analysis и остальные additive-возможности реализуются по тому же документу без изменения границ модулей.

### Этап 2. backend

#### 2.1 Продуктовый каркас

- Создать by-domain FastAPI backend с отдельными БД/Redis/Taskiq и Alembic.
- Перенести пользователей, беседы, сообщения и модельные сущности без imports generation/simulation services.
- Реализовать auth, refresh cookie, ownership dependencies, единый формат ошибок.

#### 2.2 Интеграция с generation_core

- Реализовать единый `app/clients/generator.py`: httpx, API key, timeouts, bounded retries, `trust_env=False`, idempotency.
- Добавить backend worker и scheduler/watchdog.
- Реализовать generation/simulation state machines и сохранение результатов snapshots.
- Не пробрасывать внутренние core URLs и job IDs в публичные ответы.

#### 2.3 Пользовательские сценарии

- Email/OTP find-or-create, refresh rotation/reuse detection, logout и серверный отзыв сессии.
- Отправка сообщения в беседу и polling генерации.
- CRUD бесед, список/просмотр/удаление моделей и их неизменяемых версий, экспорт.
- Запуск и история симуляций конкретной версии.
- Ручной retry failed generation/simulation.
- Миграции старых данных, если production data существует: сохранить UUID/timestamps, подтвердить владение аккаунтом через OTP, конвертировать старые модели в ModelDocument 2.0; password hashes не переносить.

#### 2.4 Проверки backend

- Contract tests GeneratorClient против fake core.
- Integration с реальным core в Docker, без frontend.
- OTP expiry/cooldown/attempt limit/single-use, refresh rotation/reuse/logout и ownership для каждого ресурса.
- Недоступность core, Redis restart, duplicate submit, lost kick, stale worker, core error, malformed core result.
- Проверка, что после `done` чтение и export работают при остановленном core.

**DoD:** backend tests, Ruff и миграции зелёные; полный сценарий OTP → conversation → model → simulation → export проходит через HTTP; нет Python imports из `generation_core`; повторный submit не плодит задачи.

### Этап 3. frontend

#### 3.1 Каркас и инфраструктура

- Next.js 16 + React 19 + Bun, Tailwind 4, Base UI/shadcn pattern, Biome, FSD.
- Тонкий `src/app`, общий root shell/providers, same-origin `/api/*` rewrites через server-only `BACKEND_URL`.
- Единый ky client, Zod-схемы рядом с entities, TanStack Query для server state; Zustand только для session и drafts.
- Не переносить `NEXT_PUBLIC_API_URL` и прямые browser calls к backend/core.

#### 3.2 Auth и chats

- Единый email/OTP login, logout, access in memory, refresh bootstrap и single-flight retry после 401.
- Conversation sidebar, создание/удаление, история сообщений.
- Optimistic user message, Idempotency-Key на submit, polling активной генерации, восстановление активных задач после reload.
- Все защищённые страницы требуют входа; локальная гостевая история отсутствует.

#### 3.3 Модели и симуляции

- Перенести read-only CLD/SFD на `@xyflow/react`, equations/variables/code tabs на react-markdown.
- Отображать стадии, warnings, ошибки и retry; не показывать пустую модель как успешную.
- Показывать версии модели и привязывать simulation к выбранной версии.
- Simulation form, custom params, polling, Recharts, engine/fallback indicator, история запусков.
- Authenticated downloads Python/Vensim/XMILE через backend; корректная обработка blob и ошибок.
- Responsive layouts, keyboard/focus states, empty/loading/error states.

#### 3.4 Проверки frontend

- Сохранить component tests на Vitest/Testing Library для model/chat logic.
- Playwright против production build: OTP auth, chat, polling, model versions/tabs, simulation, export, reload и mobile.
- Отдельные тесты 401 refresh, refresh reuse/logout, duplicate-click protection и core error.
- `bun run lint`, `bunx tsc --noEmit`, `bun run build`, unit и E2E зелёные.

**DoD:** все пользовательские сценарии работают через один frontend и реальные backend/core; нет прямых запросов к gen-api; production build и E2E проходят.

### Этап 4. Интеграционный выпуск

1. Собрать весь Compose с migrate/api/worker/scheduler процессами.
2. Прогнать полный regression suite и реальные LLM smoke tests с ограниченным бюджетом.
3. Проверить параллелизм, таймауты, лимиты памяти и восстановление после перезапуска каждого сервиса.
4. Сделать dry-run миграции данных: counts по сущностям, sampling UUID/JSON, контроль ошибок, backup.
5. Развернуть staging, провести приёмку, затем production cutover через reverse proxy.
6. Сохранить прежние образы и backup для rollback; destructive DB changes выполнять только последующим отдельным выпуском.
7. Обновить README, env examples и runbook под фактические команды.

## 11. Сквозные критерии приёмки

1. **CLI parity:** generation и simulation работают без backend и возвращают те же доменные компоненты, что старая версия.
2. **Golden models:** на фиксированных LLM fixtures variables/equations/CLD/SFD/code соответствуют baseline; численные ряды совпадают в заданных допусках.
3. **Registered E2E:** OTP request/verify → conversation → message → model version → simulation → export → reload с сохранением истории.
4. **Auth security:** OTP одноразовый и ограничен по попыткам; refresh rotation отзывает старый токен; logout запрещает последующий refresh; чужой ресурс не доступен.
5. **Isolation:** backend и core независимо перезапускаются; падение одной job не влияет на другие.
6. **Idempotency:** повтор submit/retry transport error не создаёт вторую платную генерацию.
7. **Security:** произвольный Python и вредоносные equations не исполняются; все ownership/path traversal тесты проходят.
8. **Observability:** по публичному generation ID можно проследить backend job, core job, стадии, engine и причину ошибки без раскрытия секретов.
9. **Quality gates:** все стандартные lint/typecheck/unit/integration/E2E команды каждого модуля и production Docker build проходят.

## 12. Основные риски и mitigation

| Риск | Решение |
|---|---|
| PySD несовместим с новым Python/NumPy | Compatibility gate в этапе 0; отдельная версия Python только для core при необходимости |
| Потеря тонкого поведения старого генератора | Characterization fixtures до переноса; перенос стадиями без улучшения промптов |
| Дубли LLM-задач при retries/restarts | Idempotency на backend и core, persisted generator_job_id, integration tests рестартов |
| Выполнение вредоносного кода через уравнения | Не принимать Python от клиента, AST whitelist, deterministic codegen, subprocess limits |
| Рост числа контейнеров и БД | Логически разделённые DB/queues на shared PostgreSQL/Redis; независимые миграции и credentials |
| Рассинхронизация frontend/backend contracts | OpenAPI до реализации, Zod на границе, contract/E2E tests |
| OTP abuse или кража refresh | Email/IP rate limits, HMAC-хеши, atomic single-use, refresh rotation и reuse revocation |
| Нельзя безопасно откатить БД | Backup, expand/contract migrations, destructive cleanup после стабилизации |

## 13. Допущения

- `../sdcloud_old/code` является правильным исходником предметной функциональности, но не схемы нового backend.
- Сторонних клиентов старого HTTP API нет; поэтому разрешено согласованно заменить API и frontend.
- Используется только email/OTP; пароли, guest mode, OAuth и Mini Apps не добавляются.
- OpenRouter остаётся первым LLM provider; provider abstraction не должен блокировать остальную работу.
- Если production данных нет, шаг миграции данных пропускается после подтверждения, а не выполняется искусственно.
- Точные лимиты, TTL и concurrency являются начальными настройками и уточняются замерами, но должны быть configurable с первой версии.

## 14. Reliability и локальный inference 0.2.0

- generation_core принимает от LLM безопасные DSL-формулы, числа и AST-подобные строки; canonical typed AST остаётся внутренним и хранимым контрактом, поэтому backend и frontend не меняются.
- Strict JSON Schema применяется на всех LLM-стадиях. Общий bounded repair budget покрывает malformed JSON, schema/reference errors и semantic failures; неуспешный structured output не отключается молча.
- Готовая модель проходит smoke-симуляцию. SIRS дополнительно проверяется на infection/immunity-loss topology, сезонность и возможность роста; behavior benchmark выполняет полный горизонт.
- Pattern library содержит 16 archetypes, benchmark corpus — 26 описаний с поведенческими oracles для шести новых моделей.
- Добавлен `local`/`vllm` OpenAI-compatible provider и optional `generation_core/docker-compose.local-llm.yml` для 30B-A3B AWQ на NVIDIA GPU. Backend по-прежнему вызывает только gen-api; локальный inference не требует изменения продуктовых контрактов.
- Первая загрузка весов использует сеть или подготовленный cache, после неё внешние LLM API не нужны. Облачный fallback в local-режиме отсутствует.
- Проверки 0.2.0: 96 core tests, Ruff, fixture CLI/benchmark, шесть behavior-oracles и live OpenRouter predator-prey. Полный benchmark 26×3 и реальный 30B-инференс ещё не выполнены; live SIRS с остаточным `R₀ < 1` был отклонён fail-closed.

## 15. Источники анализа

- Старая предметная логика: `../sdcloud_old/code/backend/app/services/generation`, `services/graph`, `services/simulation`, `utils`.
- Старые пользовательские контракты: `../sdcloud_old/code/SPEC.md`, `backend/app/api/v1/endpoints`, `frontend/src/fsd`.
- Паттерн CLI + gen-api + Taskiq: `../piratepress/generation_core/PRD_microservice.md`.
- Паттерн разделения core/backend и файловых контрактов: `../piratepitch/generation_core/ARCHITECTURE.md`.
- HTTP orchestration: `../piratepitch/backend/app/clients/generator.py`, `generations/tasks.py`.
- Compose и разделение БД/Redis: `../piratepitch/docker-compose.yml`.
- Frontend conventions: `../piratepress/frontend/AGENTS.md`, `../piratepitch/frontend/AGENTS.md`.
