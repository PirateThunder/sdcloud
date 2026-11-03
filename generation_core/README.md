# generation_core

Автономный движок sdCloud для генерации, проверки, симуляции и анализа
системно-динамических моделей. Работает через CLI и внутренний REST API, не импортирует
backend и не зависит от frontend.

Версия — **0.2.1**. Исходная спецификация — [PRD.md](PRD.md).

## Что реализовано

- Canonical `ModelDocument` со `schema_version=2.0` и typed AST уравнений.
- Stocks, flows, auxiliaries, constants, lookup-таблицы, subscripts и dimensions.
- Проверка ссылок, топологии потоков, units, начальных значений и auxiliary-циклов.
- CLD/SFD, зависимости и петли обратной связи.
- Безопасный DSL формул и AST-подобных строк без `eval`; внутри сохраняется canonical AST.
- Многостадийная LLM-генерация: `ModelBrief → variables → equations → validation`,
  strict JSON Schema на каждой стадии, ранние repair и общий bounded budget.
- 16 validated pattern templates и smoke-симуляция готовой модели.
- Контекстные ответы, уточнения и редактирование существующей модели.
- Симуляции через PySD/SciPy: Euler, RK4, RK45, DOP853, LSODA и BDF.
- Сценарии, seeded sensitivity analysis и calibration по наблюдениям.
- Импорт Vensim/XMILE, экспорт JSON/Python/Vensim/XMILE и результатов в CSV.
- REST API с PostgreSQL/Alembic, Redis/Taskiq, идемпотентными jobs и watchdog.

LLM-режимы: `openrouter`, `local`/`vllm` и воспроизводимый `fixture`.
Численный solver внешнего LLM API не требует. Локальный provider работает с vLLM
и другими OpenAI-compatible серверами без обязательного API key и без облачного fallback.

## Структура

```text
pipeline/                 Предметная логика, IR, валидация, LLM и анализ
  simulation/             Выбор solver и SciPy runner
service/                  FastAPI, БД, Taskiq, jobs и файлы результатов
alembic/                  Миграции БД generation_core
examples/                 Примеры generation/simulation requests
tests/                    Unit/integration/API/CLI-тесты и fixtures

generate.py               Текст → модель
chat.py                   Контекстный ответ или новая версия модели
simulate.py               Модель + параметры → JSON + CSV
convert.py                Импорт/экспорт моделей
scenarios.py              Сравнение сценариев
sensitivity.py            Анализ чувствительности
calibrate.py              Подбор параметров по наблюдениям
benchmark.py              Проверка качества LLM-генерации
watchdog.py               Обработка зависших jobs
```

## Автономный CLI

Требуются Python 3.13 и [uv](https://docs.astral.sh/uv/). Команды выполняются из
`generation_core/`; PostgreSQL, Redis и Docker для CLI не нужны.

```bash
uv sync --frozen

uv run python generate.py \
  --provider fixture \
  --fixture tests/fixtures/llm_responses.json \
  --input examples/predator_prey.json \
  --workdir work/predator-prey \
  --output out/predator-prey/model.json

uv run python simulate.py \
  --model out/predator-prey/model.json \
  --params examples/simulation.json \
  --workdir work/predator-prey-simulation \
  --output out/predator-prey/simulation.json
```

После генерации появляются canonical JSON, экспортируемые модели и manifest.
Симуляция создаёт `simulation.json` и `simulation.csv`.

Для реальной генерации вместо fixture задайте в окружении:

```bash
export LLM_PROVIDER=openrouter
export OPENROUTER_API_KEY='ваш-ключ'
export OPENROUTER_MODEL='openai/gpt-4o-mini'
```

`OPENROUTER_BASE_URL`, `PROXY_URL` и `LLM_MAX_REPAIRS` можно переопределить при
необходимости. Ключи нельзя сохранять в request-файлах или коммитить в репозиторий.

Другие CLI:

```bash
uv run python chat.py --input request.json --output out/chat/response.json
uv run python convert.py import --input model.mdl --output out/imported/model.json
uv run python convert.py export --model out/imported/model.json --format python --output out/model.py
uv run python scenarios.py --model model.json --scenarios scenarios.json
uv run python sensitivity.py --model model.json --config sensitivity.json
uv run python calibrate.py --model model.json --observations observations.json
uv run python benchmark.py --runs 3 --output out/benchmark.json
```

Форматы входных JSON соответствуют Pydantic-схемам в `pipeline/schemas.py` и
`pipeline/analysis_schemas.py`. Все параметры любого CLI можно посмотреть через
`uv run python <script> --help`.

## Локальная LLM / vLLM

Для уже запущенного OpenAI-compatible сервера:

```bash
export LLM_PROVIDER=local
export LOCAL_LLM_BASE_URL=http://127.0.0.1:8000/v1
export LOCAL_LLM_MODEL='QuantTrio/Qwen3-VL-30B-A3B-Instruct-AWQ'

uv run python generate.py \
  --provider local \
  --input examples/predator_prey.json \
  --workdir work/local-predator \
  --output out/local-predator/model.json
```

`LOCAL_LLM_API_KEY` не обязателен. `LOCAL_LLM_TIMEOUT` по умолчанию 300 секунд,
`LOCAL_LLM_MAX_TOKENS` — 8192, `LOCAL_LLM_STRUCTURED_OUTPUT=1`. Неуспешный
structured output не отключается молча; fallback возможен только после явного
`LOCAL_LLM_ALLOW_UNSTRUCTURED_FALLBACK=1`.

Для автономного GPU-контура из `generation_core/`:

```bash
cp ../.env.example .env
# В .env: LLM_PROVIDER=local.
docker compose -f docker-compose.yml -f docker-compose.local-llm.yml up --build -d
curl http://127.0.0.1:8000/v1/models
```

Требуются NVIDIA GPU с 24 GB VRAM и NVIDIA Container Toolkit. Override запускает
vLLM с `QuantTrio/Qwen3-VL-30B-A3B-Instruct-AWQ`, `--max-model-len 16384` и
`--gpu-memory-utilization 0.92`. Используйте `VLLM_MODEL`, `VLLM_MAX_LEN`,
`VLLM_GPU_MEM`, `VLLM_HOST_PORT` для настройки. Первая загрузка весов требует сети
или готового кэша `${HF_HOME:-~/.cache/huggingface}` и может занимать десятки минут;
`VLLM_HEALTH_START_PERIOD=1800s` не даёт Compose преждевременно признать vLLM unhealthy.
После загрузки облачные LLM API не используются. На RTX 5090 Laptop 24 GB под WSL2
подтверждены `/v1/models`, CLI generate/simulate, REST generation/simulation и полный
продуктовый сценарий с контекстным чатом, версиями и экспортом.

Полный local benchmark 26×3 (78 cases): executable 83,3%, semantic 83,3%, behavior
75,6%, average duration 31,256 с. Все 26 описаний имеют хотя бы один semantic success;
14 имеют behavior success во всех трёх запусках. Целевые 90/85/85% пока не достигнуты.

## REST API

Для автономного Docker-запуска из `generation_core/`:

```bash
cp ../.env.example .env
# Настройте LLM и секреты в .env.
docker compose up --build -d
curl http://127.0.0.1:58312/ready
```

Поднимаются `gen-db`, `gen-redis`, `gen-migrate`, `gen-api`, `gen-worker` и
`gen-watchdog`. Не запускайте этот Compose одновременно с полным стеком из корня:
они используют один host-порт. Остановка — `docker compose down`.

В local/staging доступны Swagger UI `/docs` и OpenAPI `/openapi.json`.
Основные endpoints:

| Метод и путь | Назначение |
|---|---|
| `POST /api/v1/models` | Создать generation job |
| `POST /api/v1/chat` | Создать chat/generation job |
| `POST /api/v1/models/import` | Импортировать `.mdl` или `.xmile` |
| `POST /api/v1/simulations` | Запустить симуляцию |
| `POST /api/v1/scenario-runs` | Запустить сценарии |
| `POST /api/v1/sensitivity-runs` | Запустить sensitivity analysis |
| `POST /api/v1/calibrations` | Запустить calibration |
| `GET /api/v1/jobs/{id}` | Статус job |
| `GET /api/v1/jobs/{id}/result` | JSON-результат |
| `GET /api/v1/jobs/{id}/log` | Хвост журнала |
| `GET /api/v1/jobs/{id}/files/{filename}` | Скачать разрешённый артефакт |
| `POST /api/v1/jobs/{id}/retry` | Повторить failed job |
| `GET /health`, `GET /ready` | Health/readiness |

POST-endpoints принимают `Idempotency-Key`. Если `SERV_API_KEY` задан, endpoints
`/api/v1/*` требуют заголовок `X-API-Key`. В продуктовом контуре вызывать этот API
должен backend, а не браузер.

## Конфигурация

Все сервисные настройки имеют префикс `SERV_`.

| Переменная | Назначение / значение по умолчанию |
|---|---|
| `SERV_ENVIRONMENT` | `local`; вне local/staging OpenAPI скрывается |
| `SERV_DATABASE_URL` | PostgreSQL generation_core |
| `SERV_REDIS_URL` | Redis очереди generation_core |
| `SERV_API_KEY` | Внутренний API key; пусто — без проверки |
| `SERV_JOB_TIMEOUT` | Таймаут generation job, секунды; `600` |
| `SERV_SIMULATION_TIMEOUT` | Таймаут симуляции, секунды; `60` |
| `SERV_IMPORT_TIMEOUT` | Таймаут импорта, секунды; `60` |
| `SERV_WORKER_CONCURRENCY` | Асинхронные задачи worker; `2` |
| `SERV_JOB_MEMORY_MB` | Лимит памяти subprocess, MiB; `1024` |
| `SERV_JOB_MAX_FILE_MB` | Максимальный размер файла результата; `64` |
| `SERV_JOB_MAX_FILES` | Максимальное число файлов результата; `128` |

Шаблон также содержит `OPENROUTER_*`, `LLM_PROVIDER` и `LLM_FIXTURE_PATH`.
Полный список — в [.env.example](.env.example) и `service/config.py`.

## Разработка

```bash
uv sync --frozen
uv run pytest
uv run ruff check .
```

API-тесты используют изолированные тестовые зависимости. Live OpenRouter-тесты не
следует запускать в обычном unit-test прогоне; `benchmark.py` выполняется отдельно
и может расходовать платные LLM-запросы.

Рабочие директории `work/`, `work_api/` и результаты `out/` исключены из Git и
Docker-контекста. Dockerfile собирает production-образ без dev-зависимостей и
запускает процесс от непривилегированного пользователя.

## Ограничения

- Не каждый корректный JSON от LLM является осмысленной моделью; semantic validation
  и behavior-oracles отклоняют часть некорректных результатов, но не доказывают
  научную корректность произвольной системы.
- Поддержка вычислительно сложных моделей зависит от выбранного solver и не отменяет
  необходимости проверять устойчивость и корректность результатов.
- Benchmark 26×3 завершён: целевые 90/85/85% не достигнуты, а часть описаний имеет
  переменчивый результат между запусками; production quality gate не пройден.
