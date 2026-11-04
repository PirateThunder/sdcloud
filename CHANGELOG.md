# Changelog

Все заметные изменения sdCloud. Новые записи добавляются выше предыдущих;
исторические записи не переписываются.

Формат версий: `MAJOR.MINOR.PATCH` (0.x — до публичного запуска).
Версии компонентов хранятся в `generation_core/version.py`,
`backend/pyproject.toml` и `frontend/package.json` и обновляются синхронно.
Коммиты с заметными изменениями — с версией в сообщении: `x.y.z - что сделано`.
Для каждой записи указываем изменения, затронутые модули и выполненные проверки.

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
