# sdCloud

AI-ассистент для системной динамики: превращает текстовое описание системы в
модель с переменными, уравнениями, CLD/SFD-диаграммами и численными симуляциями.
Поддерживает контекстную беседу, версии моделей, сценарии, sensitivity analysis,
calibration и экспорт в открытые форматы.

Монорепозиторий состоит из независимого движка генерации, продуктового backend и
браузерного интерфейса. Текущая версия — **0.6.2**, статус — production profile
подготовлен, но внешний deployment с реальными доменом и SMTP не выполнялся.

## Возможности

- Генерация системно-динамических моделей из текстового описания через LLM.
- Typed component builder для систем вне библиотеки archetypes: first-order переходы,
  условные и scheduled flows, очереди, задержки и полиномиальные ODE с выводом units.
- Opt-in lexical RAG на проверенных ComponentPlan-примерах, без vector DB; по умолчанию выключен.
- Controlled evaluation: direct baseline, typed pipeline без repair и полный pipeline;
  парная статистика с учётом prompt clusters, blind expert export и Cohen's kappa.
  Протокол и offline fixture описаны в [generation_core/README](generation_core/README.md).
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
- [evaluation/controlled-local-qwen3.json](evaluation/controlled-local-qwen3.json) —
  манифест controlled ablation локальной 8B: 216 случаев и парная статистика.
- [evaluation/controlled-local-qwen3-30b.json](evaluation/controlled-local-qwen3-30b.json) —
  аналогичная серия Qwen3-30B-A3B-Q4_K_M на том же pipeline и corpus.
- [evaluation/controlled-local-qwen3-model-comparison.json](evaluation/controlled-local-qwen3-model-comparison.json) —
  парное сравнение 8B/30B; различия full pipeline статистически не значимы.
  Независимая экспертная разметка ещё не проведена.
- [evaluation/release-0.6.2.json](evaluation/release-0.6.2.json) — релизный манифест:
  archives, hardening, expert handoff, production smoke и внешние блокеры.
- [evaluation/post-benchmark-hardening.json](evaluation/post-benchmark-hardening.json) —
  targeted regression без LLM/GPU, не новый benchmark.
- [evaluation/controlled-local-qwen3-artifacts.sha256](evaluation/controlled-local-qwen3-artifacts.sha256)
  и [evaluation/expert-review-packages.sha256](evaluation/expert-review-packages.sha256) —
  контрольные суммы архивов владельца и публичного экспертного пакета.
- [paper/main.tex](paper/main.tex) — исходники магистерской работы в LaTeX;
  собранные PDF и локальные инструменты не коммитятся.

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
  `OPENROUTER_API_KEY`. Пример использует `qwen/qwen3-30b-a3b-instruct-2507`;
  `OPENROUTER_MODEL` в существующем `.env` имеет приоритет над default;
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

### Динамический 8B/30B режим (opt-in)

Для local provider можно включить `LLM_DYNAMIC_ROUTING=1`. Worker измеряет свободную VRAM
через `nvidia-smi` при каждой новой генерации и выбирает 30B при достаточном запасе, иначе 8B.
Настройки `LOCAL_LLM_LARGE_*`, `LOCAL_LLM_SMALL_*`, `LLM_LARGE_MIN_FREE_MIB` и
`LLM_DYNAMIC_LOCAL_FALLBACK` описаны в `.env.example`. Модель не меняется посреди одной
генерации: временный сбой provider повторяет весь request на другой модели, а ошибки JSON,
схемы и семантики не маскируются fallback. Маршрут и причина попыток видны в manifest и
`routing.json`; облачный fallback требует отдельного `LLM_DYNAMIC_CLOUD_FALLBACK=1`.

`generation_core/docker-compose.local-llm-dynamic.yml` — необязательный пример двух endpoints.
Он не является доказательством одновременного размещения на 24 GB: текущая 30B VL AWQ после
инициализации занимает около 20,6 GiB, а попытка уменьшить её долю до 0,73 не оставила KV-cache.
На RTX 5090 24 GB проверка выполнена последовательно; для одновременного режима нужны другие
веса, больше VRAM или несколько GPU. 30B запускается через vLLM, а 8B Q4_K_M — через llama.cpp:
vLLM 0.30.0 не поддерживает GGUF loader. Подробности и ограничения — в README движка.

## Порты

Публикуемые порты привязаны к `127.0.0.1`.

| Порт | Сервис |
|---|---|
| `56556` | frontend; изменяется через `FRONTEND_HOST_PORT` |
| `61231` | backend; изменяется через `BACK_HOST_PORT` |
| `58312` | generation_core REST API; изменяется через `GEN_HOST_PORT` |

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
Для полного Docker E2E сначала выполните `LLM_PROVIDER=fixture docker compose up --build -d`
и дождитесь `/ready` backend (`61231`) и core (`58312`). `NEXT_PUBLIC_LLM_PROVIDER`
встраивается при production build, поэтому смены runtime env без пересборки недостаточно.
После проверки верните прежний provider повторной production-сборкой.

## Конфигурация и секреты

- Корневой `.env` — источник конфигурации для Docker Compose. Он исключён из Git.
- Не помещайте ключи OpenRouter, SMTP-пароли и production-секреты в `.env.example`,
  Dockerfile, исходники или журнал.
- `SERV_API_KEY` защищает внутренний generation_core API; backend получает то же
  значение через `BACK_GENERATOR_API_KEY` в Compose.
- Для настоящей отправки писем настройте `BACK_SMTP_*`; иначе используйте только
  локальный dev-режим OTP.
- `work/`, `work_api/`, `out/`, результаты тестов и локальные симуляции не коммитятся.

## Production profile

Отдельный `docker-compose.production.yml` добавляет Caddy с автоматическим HTTPS,
healthchecks, resource limits и log rotation. Внутренние API остаются на loopback;
наружу выставляются только HTTP/HTTPS proxy. Dev OTP отключён, backend требует
непустые JWT/OTP secrets, SMTP host и sender.

1. В `.env` задайте `GEN_DB_PASSWORD`, `BACK_DB_PASSWORD`, `SERV_API_KEY`,
   `BACK_JWT_SECRET`, `BACK_OTP_SECRET`, `BACK_ENV=production`,
   `BACK_EMAIL_DEV_CODE=0`, `SDCLOUD_DOMAIN`, `SDCLOUD_TLS_EMAIL`,
   `BACK_CORS_ORIGINS=https://<домен>` и `BACK_SMTP_*`.
2. Для OpenRouter задайте `LLM_PROVIDER=openrouter` и `OPENROUTER_API_KEY`.
   Для local provider вместо этого настройте `LOCAL_LLM_BASE_URL` и
   `LOCAL_LLM_MODEL`; preflight проверит выбранный вариант.
3. Настройте DNS домена на сервер и откройте порты 80/443. Не помещайте реальные
   секреты в `.env.example`, Git или журнал.
4. Выполните проверку без запуска сервисов и без ACME-запросов:

```bash
deploy/check-production.sh
docker compose -f docker-compose.yml -f docker-compose.production.yml up --build -d
```

Caddy получает и обновляет TLS-сертификаты автоматически после корректной настройки
DNS. Его образ закреплён версией и multi-architecture digest; при необходимости
`CADDY_IMAGE` можно переопределить. `HTTP_BIND_ADDRESS`, `HTTPS_BIND_ADDRESS`,
`HTTP_PORT` и `HTTPS_PORT` настраиваются через `.env`.

Резервное копирование обеих PostgreSQL-баз:

```bash
deploy/backup.sh
# Или другой каталог: deploy/backup.sh /path/to/backups
```

Скрипт создаёт timestamped custom-format dumps и SHA-256 в `backups/` (gitignored),
не удаляя старые копии. Секреты в dumps не включаются отдельным файлом; храните
резервную конфигурацию `.env` независимо и защищённо. Восстановление проверяйте на
отдельном окружении перед production-заменой.

Реальный внешний deployment, DNS/ACME и SMTP-доставка в этом репозитории не
выполнялись. Проверены preflight и изолированный локальный production-config smoke.

## Текущие ограничения

- Реальный 30B-инференс проверен на RTX 5090 Laptop 24 GB под WSL2: CLI generate/simulate,
  REST jobs и продуктовый чат работают; качество зависит от конкретного запроса и модели.
- Качество генерации сложных моделей зависит от LLM; bounded repair и semantic checks
  могут отклонить модель вместо возврата некорректного результата.
- Текущий local benchmark 26×3 (78 cases) достиг 98,7% по всем метрикам; held-out 16×3
  достиг 97,9% executable/semantic и 95,8% behavior на RTX 5090 с локальной 30B.
  Исходный OpenRouter 26×3 достиг 94,87%; confirmation v16 — 95,83%/93,75%,
  validation v13 — 100%. Эти результаты относятся к известным archetypes.
- Independent corpus из 14 новых предметных областей не совпадает с archetype metrics.
  Полный v6 (`out/benchmark-openrouter-independent-14x3-v6.json`) достиг 90,48%
  executable/semantic/behavior при repair rate 26,19%; targets 90/85/85% пройдены
  на этом corpus. FitzHugh остался 0/3, transport 2/3, поэтому универсальная
  стабильность не заявляется. Отдельный confirmation 10×3 (`out/benchmark-openrouter-independent-confirmation-10x3-v3.json`)
  достиг 96,67% executable/semantic и 90% behavior при repair rate 16,67%. Targets пройдены,
  но nonlinear recovery имеет 2/3 executable и 1/3 behavior, а two-stage heating — 2/3 behavior.
- В версии 0.5.0 добавлены deterministic explicit ODE builder, missing-stock
  restoration, conservative delay-composition validation и нормализация inferred time settings.
  Regression acceptance2/blind достиг 100%; acceptance3 v6 и acceptance4 v5 также достигли 100%
  executable/semantic/behavior/graph (24/24 и 18/18). Независимый acceptance4 v1 ранее подтвердил
  100% на новых описаниях. Универсальная стабильность не заявляется: отдельные LLM-ответы
  могут исчерпать bounded repair и быть отклонены вместо возврата некорректной модели.
- Внешний SDXorg corpus зафиксирован отдельно от LLM metrics: 154 Vensim-файла,
  148 с эталоном, **63 imported, 63 simulated, 62 matched** при неизменных `rtol=1e-3`
  и `atol=1e-5`. Поддерживаются dimensions, indexed references, numeric multidimensional
  и partial arrays, element-specific stock derivatives, aliases/subranges, `:EXCEPT:` и
  ограниченные expression/stock/local/nested macros. Rössler — отдельный numerical
  compatibility case: эталонный Euler float32 совпадает во всех 9603 stock-точках;
  обычный float64 имеет 52 точки возле нуля вне допуска. Основной solver не переключался.
- Текущая локальная 30B на RTX 5090: acceptance2 — 95,83%, acceptance3 — 100% executable/semantic
  и 87,5% behavior, acceptance4 — 100% по всем метрикам. Пороги 90/85/85 выполнены;
  остаточные ошибки composition/topology не скрываются.
- Qwen3-8B-Q4_K_M проверен на 70 cases: 72,86% executable/semantic и 71,43% behavior.
  Целевые показатели не достигнуты, поэтому стабильная замена 30B не подтверждена.
  14B и дополнительные live robustness/long-context отложены; vLLM после 8B остановлен.
- В сопоставимом controlled ablation на одном pipeline full 30B-A3B-Q4_K_M достиг
  **98,61% executable, 90,28% semantic и 88,89% behavior** (216 случаев), а full 8B —
  94,44%/87,50%/84,72%. Парная разница 30B − 8B не статистически значима: для behavior
  +4,17 п.п., CI [−1,39; 11,11], Holm p=1,0. Это сравнение dense 8B и MoE 30B-A3B,
  а не изолированный эффект размера. Независимая экспертная разметка ещё не проведена.
  После 30B evaluation-сервер и monitor остановлены, временные контейнеры удалены.
- Редактор CLD/SFD и автоматическая симуляция после каждой генерации не входят
  в текущую версию.

## Версионирование

Используется `MAJOR.MINOR.PATCH`; до публичного запуска — версии `0.x`.
Заметные изменения добавляются в [CHANGELOG.md](CHANGELOG.md), а версии модулей
обновляются синхронно. Формат сообщений коммитов: `x.y.z - что сделано`.
