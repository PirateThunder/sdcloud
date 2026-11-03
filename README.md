# sdCloud

AI-ассистент для системной динамики: превращает текстовое описание системы в
модель с переменными, уравнениями, CLD/SFD-диаграммами и численными симуляциями.
Поддерживает контекстную беседу, версии моделей, сценарии, sensitivity analysis,
calibration и экспорт в открытые форматы.

Монорепозиторий состоит из независимого движка генерации, продуктового backend и
браузерного интерфейса. Текущая версия — **0.2.1**, статус — локальная разработка,
не production release.

## Возможности

- Генерация системно-динамических моделей из текстового описания через LLM.
- Stocks, flows, auxiliaries, constants, typed AST, проверка units и топологии.
- Контекстный чат: вопросы о модели, уточнения и изменения текущей версии.
- CLD/SFD, поиск петель обратной связи и просмотр уравнений в LaTeX.
- Симуляции через PySD/SciPy с сохранением истории и экспортом CSV.
- Сценарии, sensitivity analysis, calibration, импорт Vensim/XMILE и экспорт
  Python/Vensim/XMILE.
- Регистрация и вход по email/OTP; гостевого доступа нет.
- Приватные беседы, модели, неизменяемые версии и запуски симуляций.

## Состав

| Каталог | Назначение | Стек | Документация |
|---|---|---|---|
| `generation_core/` | Движок генерации, симуляции и анализа; CLI и внутренний REST API | Python 3.13, FastAPI, PySD, SciPy, PostgreSQL, Redis, Taskiq | [README](generation_core/README.md) · [PRD](generation_core/PRD.md) |
| `backend/` | Пользователи, email/OTP, беседы, модели, версии и запуски симуляций | Python 3.13, FastAPI, SQLAlchemy, PostgreSQL, Redis, Taskiq | [README](backend/README.md) |
| `frontend/` | Лендинг и браузерное рабочее пространство | Next.js 16, React 19, TypeScript, Bun, FSD, Tailwind CSS | [README](frontend/README.md) |

Дополнительные документы:

- [PRD.md](PRD.md) — требования, архитектура и критерии приёмки всего продукта.
- [CHANGELOG.md](CHANGELOG.md) — история заметных изменений.
- [.env.example](.env.example) — шаблон конфигурации без реальных секретов.

## Архитектура

```text
Браузер
   │ same-origin /api/*
   ▼
frontend :56556
   │ HTTP rewrites
   ▼
backend back-api :61230 ───────────────► back-db / PostgreSQL
   │                                           back-redis / Redis
   │ HTTP + X-API-Key + Idempotency-Key        back-worker
   ▼                                           back-watchdog / scheduler
generation_core gen-api :58312 ──────────► gen-db / PostgreSQL
                                              gen-redis / Redis
                                              gen-worker
                                              gen-watchdog
```

Основные границы:

- frontend обращается только к backend;
- backend обращается к generation_core только по HTTP, без импорта его кода;
- backend и generation_core имеют отдельные PostgreSQL, Redis и миграции;
- длительные задачи выполняют workers, а не HTTP-запросы;
- generation_core — внутренний сервис, а не публичный API конечных пользователей.

## Быстрый старт

Требуются Docker с Docker Compose. Для разработки без Docker — Python 3.13,
uv и Bun; подробности есть в README модулей.

```bash
git clone git@github.com:PirateThunder/sdcloud.git
cd sdcloud
cp .env.example .env
```

Перед запуском выберите режим LLM в `.env`:

- `LLM_PROVIDER=openrouter` — реальная генерация; задайте
  `OPENROUTER_API_KEY` и при необходимости `OPENROUTER_MODEL`;
- `LLM_PROVIDER=fixture` — заготовленные ответы для воспроизводимых проверок,
  а не полноценный чат и не генератор произвольных моделей.

Запуск всего стека:

```bash
docker compose up --build -d
docker compose ps

curl http://127.0.0.1:58312/ready   # generation_core
curl http://127.0.0.1:61231/ready   # backend
```

Откройте **http://127.0.0.1:56556**. В локальном режиме
`BACK_EMAIL_DEV_CODE=1` код входа возвращается в ответе запроса OTP и показывается
в интерфейсе; SMTP для разработки не обязателен. Не включайте этот режим в production.

Полезные команды:

```bash
docker compose logs -f back-api back-worker gen-api gen-worker
docker compose up --build -d          # пересборка после изменений
docker compose down                   # остановка без удаления томов БД
```

## Локальная LLM без облака

Опциональный vLLM-контур рассчитан на NVIDIA GPU с 24 GB VRAM и NVIDIA Container
Toolkit. По умолчанию используется `QuantTrio/Qwen3-VL-30B-A3B-Instruct-AWQ` с
контекстом 16384; модель и параметры GPU меняются через `VLLM_*` в `.env`.

```bash
# В .env: LLM_PROVIDER=local. OPENROUTER_API_KEY не нужен.
docker compose -f docker-compose.yml \
  -f generation_core/docker-compose.local-llm.yml up --build -d

curl http://127.0.0.1:8000/v1/models
curl http://127.0.0.1:58312/ready
```

Внутри Docker generation_core обращается к `http://vllm:8000/v1`. Первая загрузка
весов требует сети либо заранее заполненного `${HF_HOME:-~/.cache/huggingface}` и может
занимать десятки минут; ожидание healthcheck настраивается через
`VLLM_HEALTH_START_PERIOD=1800s`. После этого inference выполняется локально. Для уже запущенного OpenAI-compatible
сервера используйте `LOCAL_LLM_BASE_URL`, `LOCAL_LLM_MODEL` и при необходимости
`LOCAL_LLM_API_KEY`. Подробности — в [generation_core/README](generation_core/README.md).

## Порты

Публикуемые порты привязаны к `127.0.0.1`.

| Порт | Сервис |
|---|---|
| `56556` | frontend; изменяется через `FRONTEND_HOST_PORT` |
| `61231` | backend; изменяется через `BACK_HOST_PORT` |
| `58312` | generation_core REST API |

PostgreSQL и Redis доступны только внутри Docker-сети. Внутри сети frontend,
backend и generation_core используют порты `54733`, `61230` и `58312` соответственно.

## Разработка и проверки

Команды выполняются из каталога соответствующего модуля.

| Модуль | Тесты | Линт / типы / сборка |
|---|---|---|
| `generation_core/` | `uv run pytest` | `uv run ruff check .` |
| `backend/` | `uv run pytest` | `uv run ruff check .` |
| `frontend/` | `bun run test` | `bun run lint`, `bunx tsc --noEmit`, `bun run build` |

Браузерные E2E-тесты frontend требуют работающий стек с локальным OTP и собранное
приложение:

```bash
cd frontend
bun run build
bun run test:e2e
```

Playwright использует уже запущенный `127.0.0.1:56556` либо сам поднимает
production-сервер frontend. Backend и generation_core при этом должны быть доступны.

## Конфигурация и секреты

- Корневой `.env` — источник конфигурации для Docker Compose. Он исключён из Git.
- Не помещайте ключи OpenRouter, SMTP-пароли и production-секреты в `.env.example`,
  Dockerfile, исходники или журнал.
- `SERV_API_KEY` защищает внутренний generation_core API; backend получает то же
  значение через `BACK_GENERATOR_API_KEY` в Compose.
- Для настоящей отправки писем настройте `BACK_SMTP_*`; иначе используйте только
  локальный dev-режим OTP.
- `work/`, `work_api/`, `out/`, результаты тестов и локальные симуляции не коммитятся.

Production-override, HTTPS, публичное развёртывание и release-процедура пока не
реализованы. Перед production-запуском необходимо заменить dev-секреты, настроить
SMTP, ограничить доступ к внутренним сервисам и выполнить полную приёмку.

## Текущие ограничения

- Реальный 30B-инференс проверен на RTX 5090 Laptop 24 GB под WSL2: CLI generate/simulate,
  REST jobs и продуктовый чат работают; качество зависит от конкретного запроса и модели.
- Качество генерации сложных моделей зависит от LLM; bounded repair и semantic checks
  могут отклонить модель вместо возврата некорректного результата.
- Полный local benchmark 26×3 (78 cases): executable 83,3%, semantic 83,3%, behavior
  75,6%; целевые 90/85/85% пока не достигнуты, поэтому production quality gate не пройден.
- Редактор CLD/SFD и автоматическая симуляция после каждой генерации не входят
  в текущую версию.

## Версионирование

Используется `MAJOR.MINOR.PATCH`; до публичного запуска — версии `0.x`.
Заметные изменения добавляются в [CHANGELOG.md](CHANGELOG.md), а версии модулей
обновляются синхронно. Формат сообщений коммитов: `x.y.z - что сделано`.
