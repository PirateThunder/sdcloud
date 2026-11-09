# generation_core

Автономный движок sdCloud для генерации, проверки, симуляции и анализа
системно-динамических моделей. Работает через CLI и внутренний REST API, не импортирует
backend и не зависит от frontend.

Версия — **0.6.2**. Исходная спецификация — [PRD.md](PRD.md).

## Что реализовано

- Canonical `ModelDocument` со `schema_version=2.0` и typed AST уравнений.
- Stocks, flows, auxiliaries, constants, lookup-таблицы, subscripts и dimensions.
- Проверка ссылок, топологии потоков, units, начальных значений и auxiliary-циклов.
- CLD/SFD, зависимости и петли обратной связи.
- Безопасный DSL формул и AST-подобных строк без `eval`; внутри сохраняется canonical AST.
- Многостадийная LLM-генерация: `ModelBrief → component plan → variables → equations → validation`,
  ранние repair и общий bounded budget. Для новых систем вне pattern library typed
  component plan заменяет свободные variables/equations детерминированным builder.
  Component plan использует JSON-only decoding с обязательной Pydantic-валидацией;
  для совместимых endpoints полная schema включается через `LLM_COMPONENT_STRUCTURED_OUTPUT=1`.
  Остальные LLM-стадии сохраняют strict JSON Schema.
- Шесть typed mechanisms: `first_order`, `conditional_inflow`, `queue`, `scheduled_flow`,
  `delay` и `polynomial_ode`. Builder выводит units коэффициентов, объединяет повторные
  stocks каскада только при совпадении initial/units и идентичные shared parameters.
  Redundant parameters удаляются только при совпадении с numeric coefficient; остальные
  неиспользуемые parameters отклоняются. `scheduled_flow` поддерживает знакопеременный
  net inflow из cloud в stock; отрицательный однонаправленный outflow запрещён.
- Для явных `dX/dt = …` deterministic AST builder сохраняет исходные коэффициенты и
  факторизованную форму без LLM-переписывания. Numerical equivalence probe проверяет
  поддерживаемые выражения на нескольких наборах значений без `eval`; неоднозначный текст
  пропускается без угадывания. Размерности numeric literals выводятся из ограничений
  уравнения (например, верхняя ёмкость в `1-stock/capacity`), а не из названия предметной области.
  Inferred `time_step` ограничивается для delay и self-decay с учётом ошибки Euler,
  с ограничением 10000 внутренних шагов; явно заданный пользователем шаг не перезаписывается.
- 16 validated pattern templates и smoke-симуляция готовой модели. Opt-in
  `LLM_PATTERN_SHORTCUT=1` использует pattern без LLM только если все числа описания уже
  принадлежат ему и нет конфликта временных/физических единиц. Custom values отключают shortcut.
  Для Lorenz/Van der Pol/Duffing, SIRS и student club canonical flows/auxiliaries берутся из
  validated pattern, а initial/constants сохраняются. Остальные модели используют LLM pipeline.
- Канонические SI и составные units, безопасная нормализация unquoted numeric arithmetic
  через DSL без `eval`, behavioral oracles и independent corpus из 14 предметных областей.
- Контекстные ответы, уточнения и редактирование существующей модели.
- Симуляции через PySD/SciPy: Euler, RK4, RK45, DOP853, LSODA и BDF.
- Сценарии, seeded sensitivity analysis и calibration по наблюдениям.
- Импорт Vensim/XMILE, экспорт JSON/Python/Vensim/XMILE и результатов в CSV.
- REST API с PostgreSQL/Alembic, Redis/Taskiq, идемпотентными jobs и watchdog.

LLM-режимы: `openrouter`, `local`/`vllm` и воспроизводимый `fixture`.
Численный solver внешнего LLM API не требует. Локальный provider работает с vLLM
и другими OpenAI-compatible серверами без обязательного API key; облачный fallback по умолчанию
выключен и требует отдельного явного разрешения в dynamic mode.

### Opt-in выбор 8B/30B по VRAM

`LLM_DYNAMIC_ROUTING=1` включает `pipeline/routing.py` только для local/vLLM provider.
При создании каждой генерации worker выполняет `nvidia-smi` (локально или через
`LLM_VRAM_SSH_TARGET`) и выбирает `LOCAL_LLM_LARGE_MODEL`, если свободно не менее
`LLM_LARGE_MIN_FREE_MIB` MiB, иначе `LOCAL_LLM_SMALL_MODEL`. Модель закрепляется на весь
`brief → components → variables → equations → validation` цикл. Значения `LOCAL_LLM_*_BASE_URL`
должны указывать на уже запущенные OpenAI-compatible endpoints; router сам не скачивает и
не запускает веса.

При `LLM_DYNAMIC_LOCAL_FALLBACK=1` transport error, timeout, HTTP 408/409/425/429 или 5xx
повторяет **всю генерацию с начала** на другой локальной модели. `HTTP 400`, malformed JSON,
`ModelValidationError` и другие ошибки схемы/семантики не скрываются сменой модели. Выбранная
модель, VRAM, threshold и предыдущие provider errors сохраняются в `routing.json`, `generation_log`
и `manifest.llm_routing`; workdir попыток разделены (`attempt_1_large`, `attempt_2_small`).
`LLM_DYNAMIC_CLOUD_FALLBACK=1` — отдельное явное разрешение на OpenRouter, при отсутствии VRAM
оно также записывается как cloud route. По умолчанию оба fallback-режима не меняют старый
`LLM_DYNAMIC_ROUTING=0` provider.

Для двух endpoints есть `docker-compose.local-llm-dynamic.yml`; он требует отдельного VRAM
профилирования и не включён по умолчанию. На RTX 5090 24 GB конкретная пара
`Qwen3-VL-30B-A3B-Instruct-AWQ` и `Qwen3-8B-Q4_K_M` не помещается одновременно с рабочим
KV-cache: первая попытка 30B с `gpu_memory_utilization=0.73` завершилась `No available memory
for the cache blocks`. Поэтому GPU-проверка этой ревизии выполняется последовательно;
dual overlay предназначен для достаточно большого GPU/нескольких GPU или других весов и не
является подтверждённым production default. Для remote WSL задайте
`LLM_VRAM_NVIDIA_SMI=/usr/lib/wsl/lib/nvidia-smi` и SSH-параметры только в локальном `.env`.
SSH target, пароли и ключи не коммитятся.
Для dynamic mode `LOCAL_LLM_LARGE_MAX_TOKENS` и `LOCAL_LLM_SMALL_MAX_TOKENS` по умолчанию
равны 4096 (явный `LOCAL_LLM_MAX_TOKENS` имеет приоритет при ручном CLI-запуске). Это не меняет
старый non-dynamic default 8192 и предотвращает превышение контекста 8192 на small endpoint.

В проверенной конфигурации 30B работает через vLLM, а 8B GGUF — через
`ghcr.io/ggml-org/llama.cpp:server-cuda`. vLLM 0.30.0 отклоняет `load_format=gguf`, поэтому
один vLLM-образ для обоих файлов не подходит. llama.cpp требует только путь к `.gguf`;
`LOCAL_LLM_SMALL_MODEL` в HTTP-запросе должен совпадать с `--alias` (в примере — `small`).
Для воспроизведения используется файл `Qwen3-8B-Q4_K_M.gguf` размером 5 027 783 488 байт,
revision `7c41481f57cb95916b40956ab2f0b139b296d974`. Если cache отличается, путь меняется через
`LLAMA_SMALL_MODEL`, без изменения кода router.

Фактический GPU-smoke: dynamic 30B (`out/dynamic-large-route/manifest.json`) завершил модель за
232,599 с после недоступного small endpoint, `free_vram_mib=3540`, `fallback=true`; dynamic 8B
(`out/dynamic-small-route-v2/manifest.json`) завершил модель за 44,806 с после остановленного
large endpoint, `free_vram_mib=17934`, `fallback=true`. Обе модели имеют `validation.status=passed`
и экспорты Python/Vensim/XMILE. Первая 8B-попытка с 2048 output tokens была отклонена как
truncated; успешный повтор использовал 4096, без изменения semantic validation. Дополнительный
high-VRAM smoke при `free_vram_mib=3540`, `threshold_mib=3000` выбрал large напрямую,
`fallback=false`, и вернул `{"ok": true}`.

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
benchmark.py              Controlled ablation и проверка качества LLM-генерации
evaluate.py               Offline paired stats, expert export и agreement
external_benchmark.py     Импорт и сравнение внешних моделей без LLM
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
export OPENROUTER_MODEL='qwen/qwen3-30b-a3b-instruct-2507'
```

`OPENROUTER_BASE_URL`, `PROXY_URL` и `LLM_MAX_REPAIRS` можно переопределить при
необходимости. `LLM_REQUEST_RETRIES=5` и `LLM_RETRY_DELAY=2` задают экспоненциальный retry
временных HTTP/network ошибок; лимит repairs модели — отдельная настройка. HTTP 429 и другие
инфраструктурные ошибки помечаются в benchmark, но не исключаются из знаменателя метрик.
Ключи нельзя сохранять в request-файлах или коммитить в репозиторий.

Для воспроизведения текущего 8B-эксперимента используется
`OPENROUTER_MODEL=mistralai/ministral-8b-2512` через официальный Mistral endpoint.
Endpoint не публикует quantization, поэтому bf16 или иной формат не предполагается.
`OPENROUTER_PROVIDER_ORDER=Mistral` фиксирует провайдера, а
`OPENROUTER_ALLOW_PROVIDER_FALLBACK=0` запрещает скрытую смену провайдера; запрос также
содержит `require_parameters=true`. Настройки прогона: `LLM_SEED=2026`,
`LLM_STRUCTURED_OUTPUT=1`, `LLM_COMPONENT_STRUCTURED_OUTPUT=1`, `LLM_PATTERN_SHORTCUT=1`,
`LLM_ALLOW_UNSTRUCTURED_FALLBACK=0`, `LLM_RAG_ENABLED=0`,
`--concurrency 1 --max-repairs 2`. Это отдельная измеряемая конфигурация, а не утверждение,
что любой endpoint или квантование той же модели даст тот же результат.

Другие CLI:

```bash
uv run python chat.py --input request.json --output out/chat/response.json
uv run python convert.py import --input model.mdl --output out/imported/model.json
uv run python convert.py export --model out/imported/model.json --format python --output out/model.py
uv run python scenarios.py --model model.json --scenarios scenarios.json
uv run python sensitivity.py --model model.json --config sensitivity.json
uv run python calibrate.py --model model.json --observations observations.json
uv run python benchmark.py --runs 3 --output out/benchmark.json
uv run python benchmark.py --runs 3 \
  --prompts-file pipeline/benchmark_holdout_prompts.json \
  --output out/benchmark-holdout.json \
  --artifacts-dir out/benchmark-holdout-artifacts
uv run python benchmark.py --runs 3 \
  --prompts-file pipeline/benchmark_independent_prompts.json \
  --output out/benchmark-independent.json
uv run python benchmark.py --runs 3 \
  --prompts-file pipeline/benchmark_independent_confirmation_prompts.json \
  --output out/benchmark-independent-confirmation.json
uv run python external_benchmark.py \
  --root out/sdxorg-test-models \
  --output out/sdx-vensim.json
```

`benchmark_holdout_prompts.json` содержит 16 описаний, по одному на archetype, и
используется как validation-corpus для текущих итераций. `benchmark_confirmation_prompts.json`
содержит отдельный confirmation-набор archetypes, чьи metrics измеряются независимо.
`benchmark_independent_prompts.json` содержит 14 описаний вне pattern library, а
`benchmark_independent_confirmation_prompts.json` — ещё 10 для проверки переноса;
их метрики нельзя смешивать с archetype metrics или development-independent corpus.
Offline-тест проверяет выбор archetype на всех corpus.

`external_benchmark.py` не вызывает LLM. Он импортирует `.mdl`/`.xmile`, запускает исходные
time settings и сравнивает stocks с `output.tab`/`output.csv` поточечно (`rtol=0.001`,
`atol=1e-5` по умолчанию). Пустые необязательные reference-ячейки пропускаются; отсутствие
числовых stock-точек не засчитывается. Для stock-free моделей сравниваются запрошенные
в reference auxiliary-ряды, а не каждая внутренняя вспомогательная переменная. Отчёт разделяет
no reference, import, simulation, reference и comparison stages. Для
[SDXorg/test-models](https://github.com/SDXorg/test-models) зафиксирован commit
`21aab02739dc5187bc9564e4d3de14e575905d2f`: 154 Vensim-файла,
148 с эталоном, **63 imported, 63 simulated, 62 matched** без изменения допусков.
Поддерживаются dimensions, indexed references, numeric multidimensional и partial arrays,
element-specific stock derivatives, aliases/subranges, `:EXCEPT:` и ограниченные
expression/stock/local/nested macros. Rössler в основном float64 solver сохраняет 52 точки
возле нуля вне допуска; независимая проверка Euler float32 воспроизвела все 9603 stock-точки
эталона с нулём ошибок. Это не причина менять solver или допуски глобально. Такая проверка
оценивает interoperability, а не генерацию и не готовый text-to-model training dataset.
`--artifacts-dir` дополнительно сохраняет prompt, model, simulation, успешные ответы LLM
и стадии каждого случая. При повторе прежние JSON-стадии того же случая очищаются.
Отчёт содержит SHA-256 corpus и pipeline, max repairs, concurrency и настройки LLM.
По умолчанию `--concurrency 1`, что подходит для локальной GPU. Для облачного benchmark
можно явно задать небольшой лимит, например `--concurrency 2`; порядок результатов
и изоляция workdir сохраняются. `benchmark_robustness_prompts.json` добавляет 17 новых
русских/английских и negative cases; `outcome_pass` для модели требует прохождения behavior,
а для `expected_error` — диагностики с указанным кодом. `model_cases` и `expected_error_cases`
позволяют не смешивать эти два класса проверок. PDE/Wiener noise и обратный явный интервал
`initial_time/final_time` отклоняются до LLM-запроса.

Форматы входных JSON соответствуют Pydantic-схемам в `pipeline/schemas.py` и
`pipeline/analysis_schemas.py`. Все параметры любого CLI можно посмотреть через
`uv run python <script> --help`.

## Controlled evaluation и независимая разметка

`benchmark.py --mode ablation` последовательно запускает три варианта на одних
`prompt_id/run`, одном LLM и с одинаковым лимитом concurrency:

- `direct`: один JSON-ответ со всеми уравнениями, без ModelBrief, ComponentPlan,
  pattern library, RAG и repair. Общие bounded AST, canonical normalization, validation,
  smoke simulation и exports сохраняются: произвольный Python не выполняется ни в одном
  варианте. Отсутствие `pattern_id` у direct не считается semantic error; эталонный
  pattern используется только как oracle при оценке, но не передаётся генератору.
- `typed_no_repair`: текущий typed/pattern pipeline с `max_repairs=0`.
- `full`: тот же pipeline с общим bounded repair budget (по умолчанию 2).

Отдельный режим `--mode direct|typed_no_repair|full` запускает один вариант. Отчёт
ablation содержит SHA-256 corpus, pipeline source и `pipeline/evaluation_protocol.json`,
модель и настройки LLM, фактические отклонения от протокола и результаты каждого case.
`LLM_SEED` или `LOCAL_LLM_SEED` задаёт base seed в OpenAI-compatible запросе. В benchmark
run с нулевым индексом `r` используется `base_seed + r`: одинаковый `prompt_id/run` получает
один seed во всех arms и сравниваемых моделях, а повторы не дублируют один детерминированный
запрос. Фактический seed сохраняется в каждом case. `--seed` относится только к статистике и
expert export. Seed не гарантирует побайтовую воспроизводимость стороннего inference.

Полный offline smoke без сети:

```bash
uv run python benchmark.py \
  --provider fixture \
  --fixture tests/fixtures/llm_ablation_responses.json \
  --mode ablation \
  --prompt-ids predator_prey_ru \
  --corpus-role regression \
  --bootstrap-samples 200 \
  --seed 19 \
  --artifacts-dir out/cli-ablation-artifacts \
  --annotations out/cli-annotations \
  --output out/cli-ablation.json

uv run python evaluate.py compare \
  --report out/cli-ablation.json \
  --bootstrap-samples 200 \
  --seed 19 \
  --output out/cli-comparison.json
```

Для сравнения двух моделей на одинаковых `prompt_id/run/inference_seed` и одном pipeline:

```bash
uv run python evaluate.py compare-models \
  --baseline out/local-8b-ablation.json \
  --treatment out/local-30b-ablation.json \
  --output out/local-model-comparison.json
```

Команда сравнивает одноимённые arms и отклоняет различия corpus, pipeline, protocol,
inference settings или парных seed. Модель разрешается различать; runtime и прочие настройки
должны совпадать. Fixture подтверждает работу evaluation framework, а не качество реальной LLM. Для
confirmatory run используется новый `--prompts-file`, `--corpus-role blind`, defaults
протокола (10 000 bootstrap samples) и предварительно зафиксированные prompts/model/source.
Метка `blind` сама по себе не доказывает независимость: после просмотра результатов нельзя
подстраивать генератор под этот corpus и продолжать называть его независимым.

Для 8B-итераций `benchmark_8b_stress_prompts.json` содержит 28 development-описаний и
используется для классификации ошибок. `benchmark_confirmatory_8b_v2_prompts.json` содержит
24 других описания и закреплён тестом по SHA-256
`36f21c904440acd7dc0e25911d41e5a78c9a81a3734a9d0b517b7b2e4391be18`.
Он не входит в development или RAG corpus и запускается только после regression:
```bash
OPENROUTER_MODEL='mistralai/ministral-8b-2512' LLM_SEED=2026 \
OPENROUTER_PROVIDER_ORDER='Mistral' OPENROUTER_ALLOW_PROVIDER_FALLBACK=0 \
LLM_STRUCTURED_OUTPUT=1 LLM_COMPONENT_STRUCTURED_OUTPUT=1 LLM_PATTERN_SHORTCUT=1 \
LLM_ALLOW_UNSTRUCTURED_FALLBACK=0 LLM_RAG_ENABLED=0 \
uv run --env-file ../.env python benchmark.py \
  --provider openrouter --mode ablation \
  --prompts-file pipeline/benchmark_confirmatory_8b_v2_prompts.json \
  --runs 3 --concurrency 1 --max-repairs 2 --corpus-role blind \
  --bootstrap-samples 10000 --seed 2026 \
  --output out/openrouter-ministral8b-ablation-v2.json \
  --artifacts-dir out/openrouter-ministral8b-ablation-v2-artifacts \
  --annotations out/openrouter-ministral8b-annotations-v2
```

Controlled ablation локальных Qwen3-8B и Qwen3-30B-A3B выполнен на commit
`d7ee55d505d0f3bb360ae5adc4156e956ff6cee9` через один llama.cpp CUDA runtime с context
8192, max output 4096 и `LLM_COMPONENT_STRUCTURED_OUTPUT=0`. Для каждой модели —
24 prompts × 3 runs × 3 arms = 216 случаев; corpus, pipeline, protocol, inference seeds
и остальные LLM settings совпадают. Генератор между сериями не настраивался.

| Модель | Режим | Executable | Semantic | Behavior | Среднее время, с |
| --- | --- | ---: | ---: | ---: | ---: |
| 8B Q4_K_M | direct | 2,78% | 2,78% | 2,78% | 32,886 |
| 8B Q4_K_M | typed_no_repair | 73,61% | 69,44% | 68,06% | 23,835 |
| 8B Q4_K_M | full | 94,44% | 87,50% | 84,72% | 30,988 |
| 30B-A3B Q4_K_M | direct | 1,39% | 1,39% | 1,39% | 16,707 |
| 30B-A3B Q4_K_M | typed_no_repair | 77,78% | 70,83% | 69,44% | 14,199 |
| 30B-A3B Q4_K_M | full | **98,61%** | **90,28%** | **88,89%** | 16,532 |

Full 30B проходит инженерные пороги 90/85/85: 71/72 executable, 65/72 semantic и
64/72 behavior; repair rate — 20,83%. Full 8B проходит executable и semantic, но
behavior ниже 85% на 0,28 п.п. Это точечные оценки, а не доказательство универсальной
стабильности или превосходства одного checkpoint.

Full против typed_no_repair у 30B даёт +20,83 п.п. executable, +19,44 п.п. semantic
и +19,44 п.п. behavior без ухудшившихся пар. Для behavior 95% cluster CI —
[8,33; 31,94] п.п., Holm-adjusted p=0,000122. У 8B эффект repair составляет +16,67 п.п.
behavior (CI [8,33; 26,39], p=0,000488). Таким образом, вклад typed pipeline и repair
подтверждён отдельно в обеих конфигурациях.

`evaluate.py compare-models` выполнен для всех 72 пар каждого режима. В full разница
30B − 8B составляет +4,17 п.п. executable, +2,78 п.п. semantic и +4,17 п.п. behavior;
95% cluster CI последнего — [−1,39; 11,11] п.п., exact McNemar p=0,453125,
Holm-adjusted p=1,0. Все full-сравнения после correction имеют p=1,0: статистически
значимого преимущества 30B над 8B не выявлено. Кроме того, dense 8B и MoE 30B-A3B —
разные архитектуры, поэтому это сравнение checkpoint, а не изолированный scaling law.
Среднее время full у 30B описательно ниже (16,532 против 30,988 с); теста значимости
latency не проводилось.

Манифесты — [8B](../evaluation/controlled-local-qwen3.json) и
[30B](../evaluation/controlled-local-qwen3-30b.json), парная статистика —
[30B ablation](../evaluation/controlled-local-qwen3-30b-paired-analysis.json) и
[8B/30B comparison](../evaluation/controlled-local-qwen3-model-comparison.json).
Для 30B проверены 216 case/prompt artifacts и 128 model/simulation комплектов;
SHA-256 локального и удалённого raw report совпали. Остались восемь behavior failures:
три archetype mismatch managed forest, три relaxation cycle, отрицательный parcel buffer
и один duplicate component identifier в short infusion. Они сохранены без подстройки
под уже раскрытый corpus.

Сформированы отдельные 216 blind annotation tasks для 30B. Независимые эксперты пока не
участвовали; автоматические oracles не заменяют их разметку. После 30B inference-сервер,
benchmark container и GPU monitor остановлены, evaluation-контейнеры удалены; активных
CUDA-процессов нет, наблюдалось 487 MiB used / 23 651 MiB free. Пик мониторинга —
19 216 MiB, 75 °C и 170,87 Вт. Дополнительные GPU-запуски в этой серии не выполняются.

После controlled серий исправлены общие механизмы, а не benchmark-specific IDs:
double-count вложенных тегов archetype, русские склонения Van der Pol, эквивалентный
duplicate outflow `conditional_inflow`/`first_order`, queue timestep и проверка
stock bounds. Конфликт коэффициентов по-прежнему отклоняется, значения не
подменяются clamp. Сохранённые short infusion и parcel plans прошли targeted
regression без LLM/GPU: один компонент/уникальные IDs и неотрицательная очередь
с timestep 0,0625. Прежние проценты не пересчитывались; для оценки улучшения
нужен новый unseen corpus.

Полный архив — `out/archives/sdcloud-controlled-qwen3-0.6.2.tar.gz`, его checksum —
`evaluation/controlled-local-qwen3-artifacts.sha256`. Объединённый публичный пакет
`out/archives/sdcloud-expert-review-0.6.2.tar.gz` содержит 432 задания и 251 artifact
в анонимизированных группах A/B без answer keys. Два человека-эксперта ещё не
участвовали; приватное group mapping передавать экспертам нельзя.

Для executable/semantic/behavior рассчитываются парная разница долей, двусторонний точный
тест Макнимара и 95% percentile cluster bootstrap. Повторная выборка выполняется по целым
`prompt_id`, включая все их повторы, а не по независимым случаям. Для трёх сравнений рук
внутри каждой метрики применяется Holm correction. Targets 90/85/85 остаются инженерными
ориентирами, а не заменой paired effect и доверительного интервала.

`--annotations DIR` создаёт `expert/tasks.csv`, JSONL, отдельные model/simulation artifacts
и `annotation_guide.md`. Служебные `pattern_id`, brief, repair count, validation и
`generation_log` из expert artifacts исключены. `private/answer_key.json` нельзя передавать
экспертам. После двух независимых разметок:

```bash
uv run python evaluate.py agreement \
  --first expert-1.csv \
  --second expert-2.csv \
  --output out/annotation-agreement.json
```

Поддерживаются оценки `0`, `1`, `NA`; `behavior=1` при `semantic=0` отклоняется. Cohen's
kappa и raw agreement считаются до adjudication. `no_model` — автоматический failure и по
умолчанию исключается из expert agreement, чтобы одинаковые отказы не завышали kappa;
`--include-no-model` доступен для отдельного анализа. Offline `evaluate.py export` повторно
создаёт пакет из сохранённого ablation report.

## Lexical RAG (opt-in)

Prototype использует TF-IDF cosine retrieval по описанию и ComponentPlan, без vector DB,
embeddings или дополнительных зависимостей. Corpus содержит 24 уникальных development-описания,
по одной проверенной модели на описание; `behavior_pass` и `semantic_pass` обязательны.
Acceptance/blind corpora в retrieval не входят.

```bash
uv run python build_rag_corpus.py
# В .env: LLM_RAG_ENABLED=1
```

`LLM_RAG_CORPUS_PATH` по умолчанию — `/app/pipeline/rag_examples.json` в Docker,
`LLM_RAG_MAX_EXAMPLES=1`, `LLM_RAG_MIN_SCORE=0.08`, `LLM_RAG_MAX_CHARS=3500`.
Пример включается только целиком, без обрезанного JSON. IDs источников записываются в
`generation_log`; deterministic ODE builder, units/topology checks и bounded repair обязательны.
По умолчанию `LLM_RAG_ENABLED=0`, поэтому текущее поведение генерации не меняется.
Corpus уже включён в репозиторий; для его пересборки нужны benchmark-артефакты из `out/`.

A/B на исключённом из retrieval acceptance4 (`out/benchmark-openrouter-ab-no-rag-acceptance4-6x3.json`
и `out/benchmark-openrouter-ab-lexical-rag-acceptance4-6x3.json`): оба варианта достигли 100%
по всем метрикам. Среднее время в этом прогоне — 8,469 с без RAG и 16,381 с с RAG;
качественного преимущества не показано, поэтому prototype остаётся opt-in.

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

Текущий local benchmark на RTX 5090 (`QuantTrio/Qwen3-VL-30B-A3B-Instruct-AWQ`,
concurrency=1): исходный 26×3 — 98,7% по всем метрикам, average duration 16,49 с;
held-out 16×3 — 97,9% executable/semantic и 95,8% behavior, average duration 17,831 с.
Pipeline hash обоих — `fd76128a730941bac144ddb0d0fb987ae710bf7a93c4fa63ebdcd59ae3637017`.
Acceptance2–4 на той же 30B: acceptance2 — 95,83% по всем метрикам, acceptance3 — 100%
executable/semantic и 87,5% behavior, acceptance4 — 100% по всем метрикам. Пороги 90/85/85
выполнены; остаточные composition/topology ошибки отклоняются без ослабления validators.
Исходный OpenRouter 26×3 (`qwen/qwen3-30b-a3b-instruct-2507`): 94,87% по всем метрикам;
confirmation v16 — 95,83%/93,75%, validation v13 — 100%. Local quality gate пройден.

Frozen OpenRouter 8B regression (`mistralai/ministral-8b-2512`, `LLM_COMPONENT_STRUCTURED_OUTPUT=1`,
`LLM_PATTERN_SHORTCUT=1`, concurrency=1, seed=2026): acceptance2 — 100%, acceptance3 — 79,17%,
acceptance4 — 100%, сводно 61/66 = 92,42% executable/semantic/behavior. Stress 28 и original 26 —
100% по всем метрикам. Pipeline hash — `a5fc3038a94ea8860b80363e3f3e4d190b4bec339312d74d01f5af5d0a7bb8ff`.
Это измерения на regression/development corpus, а не универсальная гарантия для произвольных описаний.

Frozen blind ablation на 24 новых описаниях ×3: direct — 2,78%; typed_no_repair — 95,83%
executable и 90,28% semantic/behavior; full — 97,22% executable и 90,28% semantic/behavior.
Full против direct: +94,44 п.п. executable и +87,5 п.п. semantic/behavior. Full против
typed_no_repair: +1,39 п.п. executable и 0 п.п. semantic/behavior (p=1,0). Отчёт —
`out/openrouter-ministral8b-ablation-v2.json`; 216 annotation tasks и 141 model artifact —
`out/openrouter-ministral8b-annotations-v2/`. Независимые эксперты и adjudication ещё не выполнялись.

## Опциональный GGUF inference

Для vLLM 0.30 GGUF требуется официальный `vllm-gguf-plugin`; поддержка помечена
[experimental](https://docs.vllm.ai/en/latest/features/quantization/gguf/). Он нужен только
в inference-контейнере и не добавляется в зависимости generation_core. Для Qwen3 используйте
tokenizer и config базовой модели:

```bash
uv pip install vllm-gguf-plugin
vllm serve Qwen/Qwen3-8B-GGUF:Q4_K_M \
  --tokenizer Qwen/Qwen3-8B \
  --hf-config-path Qwen/Qwen3-8B \
  --max-model-len 16384
```

Для 14B аналогично используются `Qwen/Qwen3-14B-GGUF:Q4_K_M` и `Qwen/Qwen3-14B`.
`LOCAL_LLM_MODEL` должен совпадать с именем, которое сервер возвращает в `/v1/models`.
Для benchmark используется `concurrency=1`. Память, зарезервированная vLLM под KV-cache,
не является минимальным требованием модели: уменьшайте `--gpu-memory-utilization` и
`--max-model-len`, если длинный контекст не нужен. В smoke-проверке 8B Q4_K_M занимал
5 027 783 488 байт на диске; полная конфигурация с 16K context резервирует заметно больше VRAM.

Проверка 8B Q4_K_M на RTX 5090 завершена на 70 cases с `concurrency=1`:
acceptance2 — 70,83% по всем метрикам, acceptance3 — 79,17%, acceptance4 — 61,11%;
composition — 100% executable/semantic и 75% behavior. Общий результат — 72,86%
executable/semantic и 71,43% behavior. **Targets 90/85/85 не достигнуты**, поэтому
стабильная замена 30B не подтверждена. Pipeline hash —
`62695337cf3f49127909d0cb567fa98e95d37faf98c9df854ec169f851d37f91`.
Пик мониторинга — 80 °C и 176,91 Вт; после серии vLLM и SSH-туннель остановлены.
14B и дополнительные live robustness/long-context отложены, fine-tuning не выполнялся.

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
- Original/held-out archetype quality gate был достигнут на OpenRouter и локальной 30B,
  но это не production quality gate и не гарантия устойчивости вне pattern library.
- Первый independent 14×3 показал 38,1% executable/semantic и 31,0% behavior; полный v6
  после hardening достиг 90,48% по всем трём метрикам (38/42) при repair rate 26,19%.
  Это достижение targets на development-independent corpus, а не универсальная гарантия:
  FitzHugh остался 0/3, transport 2/3. Отдельный confirmation 10×3 достиг 96,67%
  executable/semantic и 90% behavior при repair rate 16,67%. Nonlinear recovery имеет
  2/3 executable и 1/3 behavior, two-stage heating — 2/3 behavior; ограничения сохраняются.
- Vensim/XMILE importer поддерживает ограниченное подмножество форматов. В SDXorg baseline
  63 из 148 reference-моделей импортированы и симулированы, 62 совпали численно; остальные
  требуют других конструкций или численной совместимости. Поддержка всего Vensim/XMILE
  не заявляется. Rössler в float64 сохраняет 52 numerical compatibility points возле нуля.
