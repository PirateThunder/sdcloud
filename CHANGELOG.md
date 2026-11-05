# Changelog

Все заметные изменения sdCloud. Новые записи добавляются выше предыдущих;
исторические записи не переписываются.

Формат версий: `MAJOR.MINOR.PATCH` (0.x — до публичного запуска).
Версии компонентов хранятся в `generation_core/version.py`,
`backend/pyproject.toml` и `frontend/package.json` и обновляются синхронно.
Коммиты с заметными изменениями — с версией в сообщении: `x.y.z - что сделано`.
Для каждой записи указываем изменения, затронутые модули и выполненные проверки.

## 0.4.0 — 2026-11-05

Семантика explicit ODE и независимая проверка обобщения.

- **Explicit ODE builder**: для распознанных `dX/dt = …` уравнений безопасный AST parser
  сам отделяет только верхнеуровневые слагаемые и внешние коэффициенты, не раскрывая скобки.
  LLM больше не может потерять outer multiplier, заменить `/3` на `3` или добавить декоративные
  parameters при переписывании явной формулы. Named parameters сохраняются только при реальном
  использовании. Дополнительная numerical equivalence probe сравнивает исходный RHS и собранную
  derivative на четырёх наборах значений через AST evaluator без `eval`; это не символьное доказательство,
  а консервативная проверка поддерживаемых выражений.
- **Prompt и repair**: факторизованная сумма остаётся одним term, delay numeric fields не принимают
  symbolic ids, а duplicate mechanisms не склеиваются автоматически с угадыванием топологии.
- **Missing-state восстановление**: непустой ComponentPlan обязан содержать все explicit ODE stocks,
  а state IDs не могут маскироваться под parameters. Если stock, initial и общие units однозначно
  заданы, builder восстанавливает пропущенный state из исходного описания вместо возврата
  статической модели; неоднозначные случаи отклоняются.
- **Component composition**: duplicate delay consumption с тем же flow или эквивалентной time
  constant отклоняется и направляется в repair. Независимый outflow с другой скоростью разрешён,
  существующие idempotent delay adapters сохранены.
- **Time settings**: непериодические inferred `time_step`/`saveper` нормализуются в divisor
  горизонта и кратный saveper. Явно заданные пользователем значения не перезаписываются.
  PySD labels с engine rounding до пяти знаков восстанавливаются в каноническую сетку только
  при совпадении длины и ошибке ≤ 5,1e-6; строгая output-grid проверка сохраняется.
- **Behavior evaluation**: stock ID с ожидаемым именем как отдельным token внутри составного ID
  разрешается только при единственном совпадении, например `warm` → `energy_in_warm_reservoir`.
  Сопоставление и простое plural resolution не зависят от регистра (`mentor` → `Mentors`).
- **Проверки**: 218 core, 20 backend и 12 frontend tests, 2/2 browser E2E; Ruff, Biome,
  TypeScript, lock-проверки и production frontend build зелёные. Acceptance2 до deterministic builder дал 83,33% по всем метрикам;
  после него тот же regression corpus достиг 100% executable/semantic/behavior (24/24), average
  6,948 с. Первый unseen blind 12×3 до deterministic builder дал 100% executable/semantic и 94,44%
  behavior; его regression после builder — 100% по всем метрикам (36/36). Acceptance3 regression
  достиг 100% executable/semantic и 95,83% behavior после missing-stock и casefold fixes.
  Эти наборы после анализа используются как regression, а не как новый independent proof.
  Live-прогоны выполнены через OpenRouter 30B без GPU.
- **Новый independent acceptance4**: `out/benchmark-openrouter-acceptance4-6x3-v1-deterministic.json`
  с шестью ранее не использованными описаниями × 3 достиг 100% executable/semantic/behavior
  (18/18) и 100% graph consistency при repair rate 27,78%, average 7,402 с. Pipeline hash —
  `0f5d29668df9e9bc10deeac4b877fc93798ee9a57c32243543e08cdd95d00374`.
- **Composition и time-grid acceptance**: после conservative delay validation, missing-stock
  restoration и engine label normalization acceptance3 v6 и acceptance4 v5 достигли 100%
  executable/semantic/behavior/graph (24/24 и 18/18), pipeline `cff52f49177a0fa4a68470a8ac9eeadf8bd7c1b52c4c9604f32ab17c8b7a10ef`.
  Acceptance2 v6 достиг 95,83% по всем метрикам (23/24); единственный malformed brief
  (массив вместо ModelBrief) был отклонён после bounded repair. Продуктовый E2E — 2/2.

## 0.3.0 — 2026-11-05

Typed component generation и независимая проверка обобщения.

- **Typed mechanisms**: для новых моделей вне pattern library добавлены `first_order`,
  `conditional_inflow`, `queue`, `scheduled_flow`, `delay` и `polynomial_ode`. Короткий
  ModelBrief отделён от ComponentPlan; валидный plan заменяет свободные variables/equations
  детерминированным builder, а пустой plan сохраняет прежний pipeline. Известные archetypes
  и редактирование base model не переключены на новый путь.
- **LLM compatibility**: component stage использует JSON-only decoding после подтверждённых
  ошибок guided decoding на 30B, но сохраняет Pydantic validation и bounded repair. Добавлены
  однозначная нормализация descriptive ids, first-order parameters и безопасный разбор
  unquoted numeric arithmetic через DSL без `eval`.
- **Topology и units**: повторные stocks каскада объединяются только при совпадающих
  initial/units/derivative/bounds; cloud не требует фиктивные units. Coefficient units
  выводятся из stock/time − expression units; SI и compound unit names нормализуются.
  Неиспользуемые ODE parameters запрещены. Additive ODE literals получают units соседних
  слагаемых без изменения формулы. `divide(a,b)` нормализуется в `div`.
- **Численная устойчивость**: isolated derivative становится эквивалентным net-flow;
  несогласованная derivative сохраняется и отклоняется. Очередь ограничивает service без
  скрытого clamp stock. Delay имеет явный initial rate; узкий delay/first_order adapter
  устраняет дублирование consumption только при совпадающей topology. При длинном горизонте
  увеличивается только SAVEPER, а TIME STEP сохраняется.
- **Behavior evaluation**: добавлены analytic exponential, monotonic, cascade, sign changes,
  delayed response, event change, steady state, range и conservation oracles. Independent
  corpus содержит 14 предметных областей, новый confirmation corpus — ещё 10 описаний вне
  pattern library. Исправлены ошибки самих oracles для equilibrium queue, finite burst и
  distributed delay; one-stock resolution не зависит от произвольного имени переменной.
- **Independent OpenRouter 14×3 v6**: 90,476% executable, semantic и behavior (38/42),
  graph consistency среди принятых 100%, repair rate 26,19%, average duration 8,811 с.
  Targets 90/85/85% достигнуты на этом development-independent corpus. Более ранний v5
  имел 38,1%/31,0%; targeted hardening не подменяет полный benchmark. FitzHugh в v6 остался
  0/3, transport 2/3, поэтому универсальная стабильность не заявляется.
- **Independent confirmation 10×3**: после исправления idempotent delay consumption,
  brief repair и conservative stock-name resolution итоговый v3 достиг 96,67%
  executable/semantic (29/30) и 90% behavior (27/30), repair rate 16,67%, average 7,751 с.
  Targets пройдены и на новом corpus. Nonlinear recovery имеет 2/3 executable и 1/3 behavior,
  two-stage heating — 2/3 behavior; validators и behavior-oracles не ослаблялись.
- **Внешняя совместимость**: новый `external_benchmark.py` проверяет внешние модели без LLM.
  Исправлены Vensim blank comments и `.Control` parsing, reference blank cells и исходный
  SAVEPER. SDXorg/test-models commit `21aab02739dc5187bc9564e4d3de14e575905d2f`:
  154 Vensim-файла, 148 с эталоном, 16 импортированы и симулированы, 15 совпали численно.
  Это отдельная interoperability-метрика, а не text-to-model dataset или LLM quality.
- **Продуктовая интеграция**: brief schema больше не отправляет provider неиспользуемые
  `$defs` component-моделей после удаления соответствующих полей; это устраняет HTTP 400
  OpenRouter на первой стадии генерации. Добавлены русские подписи `components`, `equations`
  и `smoke`, а браузерный тест не зависит от языка произвольного названия модели.
- **Проверки и границы**: 200 core, 20 backend и 12 frontend tests, 2/2 browser E2E;
  отдельный live-сценарий ceramics подтвердил сохранение typed `first_order`, LaTeX и симуляцию.
  Ruff, Biome, TypeScript, lock-проверки и production frontend build зелёные. Live-итерации выполнены только через
  OpenRouter `qwen/qwen3-30b-a3b-instruct-2507`, GPU не использовался. RAG/LoRA не начинались;
  production deployment по-прежнему не выполнялся.

## 0.2.2 — 2026-11-04

Устойчивость генерации и воспроизводимая оценка на расширенных corpus.

- **Structured generation**: non-null initial обязателен не только у stock, но и у constant;
  нулевые значения сохраняются; stock определяется также по flow endpoints, а значения
  constants сохраняются между стадиями.
  Пустой assumption.value восстанавливается только из явно заданного значения переменной.
- **Нормализация и форматы**: поддержаны wrapper calls, bracketed arguments, JSON-string AST,
  числовые shorthand `lit`, `DELAY1I/DELAY3I/SMOOTHI/SMOOTH3I` и Vensim boolean `MIN/MAX`.
  Исправлены соответствующие Vensim/XMILE round-trips и time defaults при repair.
- **Проверка качества**: smoke проходит полный горизонт, статические supply-delay модели
  отклоняются; units, topology и semantic validators не ослаблены. Bass diffusion требует
  potential adopters и word-of-mouth, а не только согласованные units.
- **Archetype selection**: добавлены предметные признаки естественных описаний; все 58
  описаний в исходном, validation и confirmation corpus выбирают ожидаемый archetype.
  Pattern передаёт initial, units, time и проверенные уравнения в коротком DSL на generation
  и repair-стадиях, вместо громоздкого AST и неявного угадывания коэффициентов.
- **Воспроизводимость benchmark**: сохраняются prompt и успешные raw LLM responses до parsing;
  прежние JSON-стадии повторяемого case очищаются. Отчёт содержит provider/model,
  structured-output settings, max repairs, concurrency, SHA-256 corpus и pipeline.
- **Пропускная способность**: опциональный `--concurrency` ограничивает одновременные запросы
  без изменения порядка результатов. Значение по умолчанию — 1 для локального inference.
- **Structural repair**: пропущенные variables сохраняются; при units-only ошибках
  kinds и topology не меняются, а при topology-ошибках можно восстановить constant.
  Undeclared ids отклоняются на equations-стадии, не доходя до полного repair.
- **Provider resilience**: network errors, HTTP 408/409/425/429 и 5xx получают ограниченные
  exponential-backoff retries; клиентские schema errors не повторяются автоматически.
  Пустой LLM content возвращает диагностику с finish_reason вместо непонятного KeyError.
- **Диагностика и артефакты**: units errors содержат операцию и размерности операндов;
  однозначные shorthand assumption paths сохраняют явно заданные initial/expression.
  Каждый завершённый benchmark-case отдельно сохраняет `case.json` до общего отчёта.
- **Domain hardening**: Bass отклоняет незапрошенный monetary budget на variables-стадии;
  equilibrium по умолчанию не подставляется в dynamic archetypes. Добавлены DSL aliases
  `Time` и `IF THEN ELSE(...)`, точные units diagnostics и проверенные supply/bullwhip repairs.
- **Canonical normalized patterns**: новые Lorenz/VDP/Duffing без explicit physical
  parameters используют equations из validated pattern вместо повторного LLM-вывода;
  initial/constants сохраняются, archetype-provenance явный. Это устраняет потерю
  размерных коэффициентов и выдуманные physical ids. Targeted oscillators v16 — 3/3.
- **Проверки**: 143 core tests, 20 backend tests, 12 frontend tests, 2/2 browser E2E,
  Ruff, Biome, TypeScript, lock-проверки и production frontend build зелёные. Полный v9:
  83,3%/83,3%/79,2%; v11: 85,4%/85,4%/83,3%; confirmation v12: 81,25% по всем метрикам —
  targets не достигнуты на тех baselines. Исходный OpenRouter 26×3: 94,87% по всем
  метрикам; confirmation v16: 95,83% executable, 95,83% semantic, 93,75% behavior —
  targets превышены. Validation v13: 100% по всем метрикам. Targeted SIR v14 — 1/1 без
  repairs; targeted Lorenz после разрешения subset exogenous inputs — 1/1 без repairs.
  Прогоны выполнены на OpenRouter 30B без GPU и затем подтверждены на локальной 30B.
- **Local acceptance**: `QuantTrio/Qwen3-VL-30B-A3B-Instruct-AWQ` на RTX 5090, concurrency=1,
  pipeline `fd76128a730941bac144ddb0d0fb987ae710bf7a93c4fa63ebdcd59ae3637017`.
  Исходный 26×3: 98,7% по всем метрикам, average 16,49 с; held-out 16×3:
  97,9% executable/semantic и 95,8% behavior, average 17,831 с. Температура под нагрузкой
  не превысила 74°C, после завершения GPU простаивает.
- **Остаточные ограничения**: отдельные LLM-ответы используют unsupported `divide`;
  корректное статическое равновесие не засчитывается как dynamic behavior. Эти случаи не
  скрыты и не привели к ослаблению validators; обязательные пороги всё равно превышены.

## 0.2.1 — 2026-11-03

Устойчивость repair и проверенный локальный inference на RTX 5090.

- **Repair**: неудачные ответы repair расходуют ограниченный бюджет вместо немедленного
  прерывания; прежние уравнения сохраняются при `null`; число попыток записывается
  и для failed benchmark cases.
- **Structured output**: kind-specific schema требует ненулевой `initial` у stock и
  запрещает `null` на уровне guided output, а не только последующей валидации.
- **Нормализация**: нулевые literals получают явные units через умножение на ноль,
  числовые формулы сворачиваются в literals, `dimensionless` приравнен к `{}`, stock
  derivative удаляется при заданной flow topology, динамические constants становятся
  auxiliaries. Импортированные модели эта generation-нормализация не изменяет.
- **Численная проверка**: smoke-симуляция выполняется на полном горизонте и входит
  в bounded repair; нестабильная модель не возвращается как готовая.
- **Локальный inference**: на RTX 5090 Laptop 24 GB под WSL2 подтверждены vLLM,
  CLI generate/simulate, REST generation/simulation и полный продуктовый сценарий
  OTP → модель → контекстный вопрос → новая версия → симуляция → Python export.
  Измеренные smoke-прогоны: predator-prey 22,6 с без repairs и teacup 14,1 с без repairs;
  около 21 ГБ VRAM и обычно 130–150 токенов/с.
- **Pattern selection**: специфичность тегов учитывается при выборе archetype;
  отдельный golden test подтверждает правильный выбор для всех 26 benchmark-описаний.
- **Полный local benchmark**: 26 описаний × 3 запуска (78 cases) на RTX 5090:
  executable 83,3%, semantic 83,3%, behavior 75,6%, средняя длительность case 31,256 с.
  Bullwhip прошёл 3/3, студенческий клуб 2/3; все 26 описаний имеют хотя бы один
  semantic success, 14 описаний имеют behavior success во всех трёх запусках.
  Целевые 90/85/85% не достигнуты; validators не ослаблены ради pass-rate.
- **Запуск**: ожидание первой загрузки весов настраивается через
  `VLLM_HEALTH_START_PERIOD`, по умолчанию 1800 секунд.

Проверки: generation_core 104 tests, backend 20 tests, frontend 12 tests и 2/2
детерминированных браузерных E2E; Ruff, TypeScript и production builds зелёные.
Production quality gate и production release не выполнены.

## 0.2.0 — 2026-11-03

Устойчивость LLM-генерации, behavior benchmark и локальный inference-контур.

- **DSL и нормализация**: LLM может возвращать короткие формулы, числа и
  AST-подобные строки; безопасный parser без `eval` преобразует их в canonical AST.
  Нормализуются function-call shorthands, `initial → expression` и numeric assumptions.
- **Structured output**: strict JSON Schema для brief, variables, equations, chat и
  repair. Несовместимость provider больше не скрывается автоматическим fallback;
  unstructured fallback доступен только через явный opt-in.
- **Repair**: общий bounded budget охватывает ранние стадии и финальную валидацию;
  добавлены проверки unknown references на variables-стадии, точные ошибки,
  сохранение repair-ответов и smoke-симуляция готовой модели.
- **Semantic и behavior checks**: SIRS проверяет infection, immunity loss,
  сезонный contact rate и возможность роста эпидемии. Benchmark выполняет полный
  горизонт и проверяет finite values, repeated waves, bullwhip, campaign wave,
  sign changes, limit cycle и two-well switching.
- **Pattern library**: 16 validated archetypes, включая SIRS, supply chain bullwhip,
  студенческий клуб, Лоренца, Ван дер Поля и Даффинга. Benchmark corpus расширен
  с 20 до 26 описаний.
- **Локальные LLM**: OpenAI-compatible provider `local`/`vllm` без обязательного
  API key и без облачного fallback. Добавлен optional Docker Compose override
  для 30B-A3B AWQ на NVIDIA GPU с контекстом 16K.
- **Документация**: обновлены PRD, корневой и модульные README, env examples и
  инструкции локального запуска.

Проверки: generation_core 96 tests, backend 20 tests, frontend 12 tests и 2/2
браузерных E2E; Ruff и production build зелёные. Все шесть behavior-oracles,
fixture CLI/benchmark и live OpenRouter predator-prey — 0 repairs, 41 simulation point,
все значения конечные. Live SIRS с остаточным `R₀ < 1` после bounded repairs был
корректно отклонён, а не выдан как готовая модель. Полный benchmark 26×3 и реальный
30B-инференс в текущем окружении не выполнялись.

## 0.1.0 — 2026-11-03

Первая модульная версия sdCloud: независимый движок генерации, продуктовый
backend и браузерное рабочее пространство вместо прежней монолитной реализации.

- **generation_core**: canonical `ModelDocument`, типизированные AST уравнений,
  stocks/flows/auxiliaries/constants, проверка units и топологии, CLD/SFD,
  библиотека системно-динамических шаблонов и ограниченный LLM repair.
- **Симуляции и анализ**: PySD/SciPy, методы Euler/RK4/RK45/DOP853/LSODA/BDF,
  lookup-таблицы, условия и события, задержки, сценарии, sensitivity analysis,
  calibration, импорт Vensim/XMILE и экспорт Python/Vensim/XMILE.
- **Интерфейсы движка**: CLI и REST API, PostgreSQL/Alembic, Taskiq + Redis,
  изолированные рабочие директории, идемпотентные задачи, watchdog и health checks.
- **Backend**: регистрация и вход по email/OTP без гостевого доступа,
  access/refresh-сессии, приватные беседы, модели, версии, симуляции и exports;
  обращение к generation_core только по HTTP.
- **Контекстный чат**: ответы и уточнения без создания модели, редактирование
  текущей модели через `base_model`, неизменяемые версии и корректный порядок
  сообщений при одинаковых timestamps.
- **Frontend**: Next.js + FSD, лендинг и кабинет, список бесед и моделей,
  просмотр CLD/SFD, запуск симуляций, интерактивные графики и экспорт CSV;
  форматирование уравнений через KaTeX.
- **Инфраструктура**: Docker Compose для всех сервисов, примеры конфигурации,
  `.gitignore`/`.dockerignore`, исключающие секреты, зависимости, кэши,
  рабочие директории и результаты локальных прогонов.
- **Документация**: корневой README с архитектурой и запуском всего стека;
  отдельные README для generation_core, backend и frontend с конфигурацией,
  CLI/API, командами разработки и проверками.

Проверки: unit/integration-тесты модулей и браузерные E2E-сценарии;
дополнительно через live OpenRouter построены и численно проверены модели
Лоренца, Ван дер Поля и Даффинга. Полный benchmark 20×3, production release
и провайдер локальных LLM ещё не выполнены.
