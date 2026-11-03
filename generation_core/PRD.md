# PRD: sdCloud Generation Core 2.0

**Статус:** этапы 0–4 и reliability/local-LLM hardening 0.2.1 реализованы; benchmark 26×3 завершён, но quality targets не достигнуты
**Владелец компонента:** `generation_core`  
**Связанный документ:** `../PRD.md`  
**Порядок:** scientific hardening → SD language + import/export → backend → advanced analysis  
**Основание:** анализ `sdcloud_old/code`, текущего `generation_core`, sdcloud.io, публикаций ИТМО и `SDXorg/test-models` / `alexprey/test-models`

## 1. Контекст

Текущий `generation_core` уже предоставляет CLI, REST API, PostgreSQL job registry, Redis/Taskiq worker, изолированные workdir, идемпотентность, PySD/SciPy simulation и экспорт Python/Vensim. Это работающая сервисная основа, но предметный контракт пока поддерживает только скалярные ODE с `INTEG`, арифметикой и небольшим набором NumPy-функций.

Проведённый анализ выявил проблемы, которые нельзя закреплять в будущих backend и frontend:

1. Нулевые stocks и constants ошибочно заменяются ненулевыми значениями.
2. Неизвестные параметры молча получают произвольные значения без явных assumptions.
3. `integration_method` не влияет на PySD: используется Euler независимо от запрошенного метода.
4. SciPy fallback заменяет Euler/RK4 на RK45, искажает временную сетку при некратном шаге и возвращает только stocks.
5. Единицы измерения хранятся, но не проверяются.
6. CLD/SFD могут не соответствовать уравнениям; structural warnings не блокируют некорректные графы.
7. Отсутствуют lookups, delays, smooth, события, условия, subscripts, Vensim/XMILE import, XMILE/CSV export.
8. Нет научного benchmark и проверки качества реального OpenRouter; текущий fixture подтверждает только работу pipeline.

Оригинальный sdCloud.io развивался как облачная среда выполнения и обмена готовыми SD-моделями, а не как text-to-model LLM generator. Его поддерживаемый модельный диалект и исследования полезны как ориентир для simulation/import/export, но не как доказательство существования AI-генерации из текста.

## 2. Цели

1. Гарантировать, что успешный результат является исполняемой и семантически проверенной SD-моделью, а не только синтаксически валидным JSON.
2. Ввести стабильный canonical ModelDocument 2.0 до появления зависимых backend/frontend.
3. Сделать численный метод, временную сетку и engine прозрачными и соответствующими фактическим вычислениям.
4. Поддержать практический базовый диалект Vensim/XMILE, включая lookups, условия, события, delays и smooth.
5. Добавить безопасный импорт существующих моделей и воспроизводимый экспорт.
6. Улучшать LLM-генерацию через проверенные примеры и измеримые validators, а не через неограниченные self-reflection/multi-agent вызовы.
7. Сохранить CLI-first и независимость core от пользователей, бесед, JWT и продуктовой БД.
8. Заложить расширение к сценариям, внешним рядам, sensitivity analysis и calibration без повторной смены основного контракта.

## 3. Принципы

1. **Canonical IR — единственный источник истины.** Python, Vensim, XMILE, CLD, SFD и simulation формируются из него.
2. **Никаких незаметных научных исправлений.** Нули сохраняются; допущения явные; запрещено silently clamp, подставлять «правдоподобные» коэффициенты или менять topology.
3. **Запрошенное не выдаётся за фактическое.** Engine, integration method, timestep, saveper и fallback фиксируются по факту.
4. **Fallback не меняет математику.** Нельзя заменять модель, метод или stateful semantics ради успешного статуса.
5. **Валидность важнее завершения любой ценой.** При ошибке возвращается actionable error, а не `done` с искажённой моделью.
6. **Графы производные, а не самостоятельные догадки LLM.** SFD строится из topology; CLD сверяется с dependency graph и polarity выражений.
7. **PySD — эталон для поддерживаемых stateful SD primitives.** SciPy обслуживает только доказанно совместимое подмножество.
8. **Никакого пользовательского Python.** Входом являются canonical JSON, Vensim или XMILE; Python всегда генерируется доверенным кодогенератором.
9. **Сначала измерение, затем оптимизация.** GPU, ErlSD, distributed per-time-step execution и fine-tuning не входят в текущий план.

## 4. Объём и приоритеты

### 4.1 Обязательно до backend

- ModelDocument 2.0 и конвертер документов 1.0.
- Удаление nonzero/default postprocess-эвристик.
- Полная корректность scalar ODE simulation.
- Units/topology/capability validation.
- Детерминированные CLD/SFD из проверенной модели.
- Базовые функции, условия, события, lookups, delay/smooth/initial.
- Vensim/XMILE import; Python/Vensim/XMILE/CSV export.
- Научные regression tests и capability matrix.
- Resource limits, watchdog и воспроизводимые manifests.

### 4.2 После стабилизации IR, до публичного релиза

- Structured ModelBrief.
- Библиотека проверенных generation patterns.
- Structured LLM output и ограниченный repair.
- Offline benchmark и ограниченный live OpenRouter evaluation.

Backend можно начинать после завершения обязательного объёма из п. 4.1. LLM quality improvements не должны снова менять IR или HTTP-контракт.

### 4.3 Последующие additive-расширения

- Subscripts и многомерные переменные.
- Внешние временные ряды.
- Сценарии и сравнение запусков.
- Seeded sensitivity analysis / Monte Carlo.
- Calibration параметров по наблюдениям.
- Исследовательское восстановление уравнений по данным мониторинга.

### 4.4 Не входит

- ABM, DES, AnyLogic и произвольные ODE/PDE вне декларированного SD-диалекта.
- Выполнение загруженного `.py`, pickle, Jupyter notebook или стороннего native-кода.
- Excel/database/external data functions в первых версиях импорта.
- Визуальный редактор модели, пользователи, совместная работа и sharing UI — это backend/frontend scope.
- Автоматическое обучение на пользовательских правках без отдельного review и evaluation.
- Обещание поддержки всего Vensim или всего XMILE без capability-тестов.

## 5. Canonical ModelDocument 2.0

### 5.1 Основные поля

Документ должен содержать:

- `schema_version: "2.0"`;
- `id`, `name`, `description`;
- `time`: `unit`, `initial_time`, `final_time`, `time_step`, `saveper`;
- `variables`: typed stock/flow/auxiliary/constant components;
- `tables`: именованные lookup tables;
- `dimensions`: зарезервированный optional contract для будущих subscripts;
- `assumptions`: явные допущения и их источники;
- `provenance`: `text_generation | vensim_import | xmile_import | migration`, исходное имя/хэш, версии parser/generator;
- `capabilities`: требуемые language/runtime features;
- `validation`: status, errors, warnings, checked capabilities;
- `cld_data`, `sfd_data`: производные представления;
- `artifacts`: metadata производных Python/Vensim/XMILE, а не второй источник уравнений;
- `created_at`, `generator_version`.

`equations` в текущем виде перестаёт быть основным хранилищем. Текстовые уравнения можно формировать как derived view для UI/export, но нельзя хранить независимую вторую версию модели.

### 5.2 Идентификаторы и отображаемые имена

- `id` — стабильный ASCII identifier для выражений, API и generated Python.
- `label` — исходное человекочитаемое имя, включая пробелы и Unicode.
- `description` — пояснение компонента.
- При импорте сохраняется mapping `id ↔ original name`; коллизии slug разрешаются детерминированным suffix.
- Зарезервированные имена `time`, `np`, Python builtins и runtime functions запрещены как `id`.
- Переименование label не меняет semantics; изменение id требует согласованного обновления всех references.

### 5.3 Переменные

| Kind | Обязательные данные | Ограничения |
|---|---|---|
| `stock` | `initial: Expression`, units, optional bounds | Начальное значение может быть нулём; не зависит от `time`, flows или runtime auxiliaries |
| `flow` | `expression`, source/target для generated model, units | Хотя бы один endpoint — stock; source и target не совпадают |
| `auxiliary` | `expression`, units | Не может содержать неразрешённый algebraic cycle |
| `constant` | finite literal или constant-foldable expression, units | Не зависит от `time` и runtime variables |

Дополнительные правила:

- `bounds: {min, max, on_violation}` описывают допустимую область, но не вызывают автоматический clipping.
- `on_violation` — `error | warn`; default для явно импортированных hard bounds — `error`.
- Отрицательные stocks разрешены, если модель явно не запрещает их.
- Для generated model каждый flow имеет ровно один `source` и один `target`, каждый из которых является stock или cloud.
- Stock derivative вычисляется как `sum(inflows) - sum(outflows)` из topology.
- Для импортированной модели допускается `stock.derivative`, если topology отсутствует или неполна. Если заданы и derivative, и topology, нормализованные выражения должны совпадать; иначе модель отклоняется.
- Неоднозначно восстановленная topology помечается `inferred/missing`; она не выдаётся за подтверждённую.

### 5.4 Typed expression AST

Внешний и хранимый формат выражений — ограниченный JSON AST, а не Python source:

```json
{"op": "lit", "value": 0.1}
{"op": "ref", "name": "growth_rate"}
{"op": "time"}
{"op": "mul", "args": [{"op": "ref", "name": "population"}, {"op": "ref", "name": "growth_rate"}]}
{"op": "call", "name": "max", "args": [{"op": "lit", "value": 0}, {"op": "ref", "name": "demand"}]}
```

Lookup имеет отдельную форму с именем зарегистрированной таблицы:

```json
{"op": "lookup", "table": "effect_of_pressure", "arg": {"op": "ref", "name": "pressure"}}
```

Требования:

- Pydantic discriminated schemas для всех AST nodes.
- Только whitelisted operators/functions и явное число аргументов.
- Все literal values конечны; booleans допускаются только в условиях.
- Нет imports, attribute access, lambda, comprehensions, assignment, dynamic indexing или arbitrary calls.
- LLM может вернуть безопасную DSL-формулу, число, canonical JSON AST или AST-подобную строку; `pipeline/expression_parser.py` нормализует их без `eval`. Внутри и при хранении используется только typed AST.
- Начальные ограничения: expression ≤ 10000 исходных символов, ≤ 500 AST nodes, глубина ≤ 50.
- Нормализация сохраняет эквивалентность и не выполняет агрессивные символические упрощения, меняющие пограничную семантику.

### 5.5 Единицы и время

Единица представляется отображением base unit → exponent:

```json
{"person": 1, "year": -1}
```

- `{}` — dimensionless; `null` — неизвестная/не распарсенная единица.
- Исходная `units_raw` сохраняется.
- Поддерживаются `*`, `/`, parentheses и integer powers.
- Alias registry версионируется; неизвестные слова не угадываются автоматически.
- Без явного conversion registry нельзя незаметно конвертировать дни/месяцы/годы.
- `time.unit` обязателен для generated model.

Проверки:

- add/sub/min/max/comparison требуют совместимые единицы.
- mul/div комбинируют exponents.
- exp/log/trigonometry принимают dimensionless аргументы.
- sqrt требует чётные exponents; power с нецелой dimensionless степенью требует поддержки rational units, иначе warning/error по capability.
- flow units = stock units / `time.unit` для каждого подключённого stock.
- delay/smooth time constants имеют `time.unit`.
- lookup декларирует input/output units.
- Вероятности и доли должны быть dimensionless и иметь bounds `[0,1]`, если это заявлено семантикой переменной.

### 5.6 Lookup tables

Таблица содержит:

- `id`, `label`;
- упорядоченные по x пары finite `(x,y)`;
- `x_units`, `y_units`;
- `interpolation: linear` — единственный обязательный режим первой версии;
- `extrapolation: clamp | linear | error`, явно сохранённый из источника; default для generated table — `clamp`.

Дублирующиеся x и пустые таблицы запрещены. Лимит первой версии — 1000 точек на таблицу. Нелинейные interpolation modes не эмулируются linear без ошибки capability.

### 5.7 Assumptions и provenance

Каждое assumption содержит:

- `path` на переменную/свойство;
- выбранное значение или описание решения;
- `source: user | archetype | llm_inferred | imported | migration`;
- понятное `rationale`;
- `requires_confirmation: boolean`.

`GenerationRequest.assumption_policy`:

- `allow_inferred` — допущения разрешены, но все попадают в результат и warnings;
- `require_explicit` — нехватка существенного параметра даёт `MISSING_PARAMETER` с путями требуемых полей.

Не должно быть постобработки, меняющей значение без связанного assumption/provenance record.

### 5.8 Capabilities

Минимальные значения:

- `scalar_ode`, `basic_math`, `conditional`, `events`, `lookup`;
- `delay`, `smooth`, `initial`;
- `subscripts`, `external_series`;
- `vensim_import`, `xmile_import` — в provenance/capability report, а не как признак исполняемости.

Для каждой модели validator вычисляет:

- `pysd_euler: supported | unsupported`, причины;
- `scipy_fixed: supported | unsupported`, причины;
- `scipy_adaptive: supported | unsupported`, причины;
- `vensim_export`, `xmile_export`, `cld`, `sfd` support и warnings.

CLI/API могут запросить только заявленную поддерживаемую комбинацию. Неподдерживаемая возможность даёт `UNSUPPORTED_CAPABILITY`, а не частичный неправильный результат.

## 6. Поддерживаемый язык уравнений

| Группа | Первая обязательная версия | Правила |
|---|---|---|
| Арифметика | `+ - * / **`, unary +/- | Finite values; переполнение/NaN/Inf — simulation error |
| Math | `exp`, `log`, `log10`, `sqrt`, `sin`, `cos`, `tan`, `power`, `abs` | Проверка domain и units |
| Min/max | `min`, `max`, `minimum`, `maximum` | Совместимые units; aliases нормализуются |
| Comparisons | `< <= > >= == !=`, `and`, `or`, `not` | Только в condition; сравниваемые units совместимы |
| Условия | `if_then_else`, безопасный conditional AST | В PySD lazy branch semantics сохраняются |
| Safe division | `xidz`, `zidz` | Соответствие Vensim/PySD semantics |
| События | `step`, `pulse`, `pulse_train`, `ramp` | Семантика привязана к integration timestep и проверяется golden tests |
| Tables | `lookup` | Только зарегистрированная таблица |
| Delays | `delay1`, `delay3` | Stateful; PySD/Euler в первой версии |
| Smoothing | `smooth`, `smooth3` | Stateful; initial value поддерживается явно |
| Initialization | `initial` | Не вычисляется повторно на каждом шаге |
| Subscripts | Отдельный последующий этап | До реализации — явный unsupported error |

`DELAY N`, `SMOOTH N`, pipeline delay, trend, sample-if-true и random functions добавляются только вместе с отдельными golden tests. Random/deterministic stochastic functions требуют явный seed и не включаются в deterministic generation suite без него.

## 7. Валидация модели

### 7.1 Уровни

1. **Schema:** типы, лимиты, references, уникальность id.
2. **Expression:** AST whitelist, arity, domains, запрещённые dependencies.
3. **Topology:** stocks/flows/clouds, отсутствие dangling flows, derivative consistency.
4. **Units:** размерный анализ и time-unit consistency.
5. **Algebraic dependencies:** auxiliary graph должен быть DAG; stock-mediated feedback разрешён.
6. **Graph consistency:** CLD/SFD соответствуют canonical dependencies/topology.
7. **Capabilities:** выбранные engine/method/export поддерживают модель.
8. **Simulation:** convergence, finite outputs, bounds, размер результата.

### 7.2 CLD

- Nodes создаются из canonical variables.
- Information links создаются из AST dependencies, а flow→stock links — из topology.
- Polarity выводится из выражения там, где она однозначна.
- При нелинейной/переменной polarity используется `unknown` либо пометка условия; запрещено угадывать `+/-`.
- LLM может предложить пояснения и предполагаемые loops, но не менять подтверждённый graph.
- `reinforcing/balancing` вычисляется только для loops с известной polarity.
- Отсутствие feedback loop — warning/характеристика модели, не обязательная ошибка.
- Дубликаты nodes/edges и unknown references — ошибки.
- Перечисление cycles ограничено; при обрезании результата выставляется `loops_truncated=true`.

### 7.3 SFD

- Flow edges создаются только из source/target topology.
- Auxiliary/constant information links создаются из AST.
- Cloud создаётся один раз на соответствующий внешний endpoint; нельзя добавлять фиктивные вторые clouds для компенсации неправильной topology.
- Stock без flow — warning или error согласно `stock.allow_isolated`; default generated model — error.
- Flow без stock, dangling flow, stock↔stock edge типа `flow`, link, заменяющий material flow, — error.
- Неполная imported topology визуально помечается и не скрывается.

### 7.4 Диагностика

Structured issue:

```json
{
  "code": "INCOMPATIBLE_UNITS",
  "severity": "error",
  "path": "variables.births.expression",
  "message": "people and people/year cannot be added",
  "hint": "Check whether births is a flow and whether its time unit is year"
}
```

`validation.status`: `passed | passed_with_warnings | failed`. Модель со статусом `failed` не может получить job `done`. Пользователю возвращаются безопасные diagnostics без stack traces, секретов и полных prompt payloads.

## 8. Simulation 2.0

### 8.1 Параметры

```text
engine: auto | pysd | scipy = auto
integration_method: euler | rk4 | rk45 | dop853 | lsoda | bdf = euler
initial_time: finite float = model.initial_time
final_time: finite float = model.final_time
time_step: float > 0 = model.time_step
saveper: float > 0 = model.saveper
parameters: dict[constant_id, finite float] = {}
stock_initial: dict[stock_id, finite float] = {}
rtol: float > 0 = 1e-6 (adaptive only)
atol: float > 0 = 1e-9 (adaptive only)
```

Старый `custom_params` разделяется на `parameters` и `stock_initial`. Произвольная замена flow/auxiliary function на константу запрещена. Unknown ids отклоняются.

### 8.2 Выбор engine

| Модель/метод | Обязательное поведение |
|---|---|
| `auto + euler`, PySD supported | PySD primary |
| PySD failure, SciPy совместим, euler | SciPy fallback с тем же методом и `fallback_reason` |
| `rk4` | SciPy fixed-step, только compatible ODE subset |
| `rk45/dop853/lsoda/bdf` | SciPy adaptive, только compatible continuous ODE subset |
| Delay/smooth/initial/events/lookup вне доказанного SciPy subset | PySD/Euler либо `UNSUPPORTED_CAPABILITY`; не подменять метод |
| Явно выбранный engine не поддерживает модель | `UNSUPPORTED_ENGINE`, без скрытого fallback |
| Несовместимость обоих engines | Ошибка с безопасными причинами обоих |

Adaptive methods не разрешены для stateful/discontinuous моделей, пока корректность не доказана тестами. Нельзя передавать Euler-модель в SciPy RK45 и выдавать результат за fallback той же симуляции.

### 8.3 Временная сетка

- `final_time > initial_time`; отрицательный `initial_time` разрешён, если модель это допускает.
- `time_step` — integration step; `saveper` — output interval.
- `(final_time - initial_time) / time_step` и `saveper / time_step` должны быть целыми в пределах числового tolerance.
- Некратная сетка отклоняется `INVALID_TIME_GRID`; запрещено незаметно менять шаг через `linspace`.
- `initial_time` и `final_time` всегда включены; output timestamps строятся от `saveper`, а не от количества точек.
- Для adaptive solver `time_step` задаёт `max_step`; `saveper` задаёт `t_eval` и не изменяет фактический integration method.
- Максимум 10 000 output points на запуск в базовой конфигурации.

### 8.4 Результат

`SimulationResult 2.0` содержит:

- `schema_version`, `model_id`, `model_hash`;
- `time` и ряды для **каждой** scalar variable: stocks, flows, auxiliaries, constants;
- выбранные/flattened series для будущих subscripts по отдельному контракту;
- `requested_engine`, `engine`, `fallback_reason`;
- `requested_method`, `integration_method` фактический;
- `time_step`, `saveper`, `rtol/atol`, если применимо;
- solver stats, если доступны: steps, evaluations, convergence;
- warnings и unit/bounds violations;
- `created_at`, `duration_seconds`.

Все series имеют одинаковую длину. NaN, Inf, несовпадение длин и неполный набор variables являются ошибкой, а не успешным частичным результатом.

### 8.5 Численные критерии

- Для fixed-step методов проверяются известные значения и порядок сходимости.
- Для adaptive методов проверяется сходимость к analytic/reference solution в заданных tolerances.
- PySD и SciPy сравниваются только на общей поддерживаемой модели, методе, timestep и output grid.
- Для stateful/discontinuous моделей используются golden outputs соответствующего PySD/Vensim semantics, а не generic RK45 как «эталон».

## 9. Import и export

### 9.1 Поддерживаемые форматы

| Формат | Import | Export | Комментарий |
|---|---|---|---|
| Canonical JSON 1.0 | Через migrator | Нет, кроме derived compatibility view при необходимости | Не исполнять сохранённый `python_code` |
| Canonical JSON 2.0 | Да | Да | Основной контракт |
| Vensim `.mdl` | Да, declared subset | Да | Сохранять labels, units, control vars |
| XMILE `.xmile` | Да, declared subset | Да | Безопасный XML, без внешних entities |
| Python `.py` | **Нет** | Да | Только trusted deterministic codegen |
| Simulation JSON | Нет как model | Да | Полные series + metadata |
| CSV | Нет в базовом import | Да | `time` + все scalar variable ids |

### 9.2 Import pipeline

`read → size/format checks → safe parse → normalize to IR → schema/AST/topology validation → capability report → exports`

- PySD parsers можно использовать как translation layer, но загруженный/translated Python не исполняется до проверки доверенного generated AST.
- DTD, external entities, network/file references и external data imports запрещены.
- Лимит исходного файла по умолчанию — 5 MiB; archive uploads не принимаются.
- Macros разворачиваются только bounded parser'ом; arbitrary code/include не поддерживаются.
- Неподдерживаемые функции собираются в capability errors с именами и путями, а не заменяются нулём/NaN.
- Неизвестная topology или units сохраняются как unknown/inferred с warning; они не выдаются за подтверждённые.
- Source hash, parser version, unsupported features и warnings попадают в manifest.

### 9.3 Export и round-trip

- Python генерируется только из IR после validation.
- Vensim/XMILE содержат model control parameters и все поддерживаемые components.
- Round-trip проверяется по semantics и numerical outputs, а не побайтовому совпадению текста.
- `IR → Vensim → IR` и `IR → XMILE → IR` не должны терять variables, topology, units, lookup points и initial values.
- CSV имеет header `time,<variable_id...>` и ту же временную сетку, что JSON.

### 9.4 CLI

```bash
uv run python generate.py --input request.json --workdir work/<id> --output out/model.json
uv run python simulate.py --model model.json --params params.json --workdir work/<id> --output out/simulation.json
uv run python convert.py import --input model.mdl --workdir work/<id> --output out/model.json
uv run python convert.py export --model model.json --format xmile --output out/model.xmile
uv run python convert.py export --model model.json --format vensim --output out/model.mdl
uv run python convert.py export --model model.json --format python --output out/model.py
```

Симуляционный CSV выгружается `simulate.py --csv out/simulation.csv` либо как стандартный artifact рядом с JSON. Все команды имеют ненулевой exit code при ошибке и не создают misleading final manifest `done`.

### 9.5 REST

Сохраняются существующие jobs API. Добавляется:

- `POST /api/v1/models/import` — upload Vensim/XMILE, `202 Accepted`, `Job(kind=import)`;
- generation job формирует `model.json`, `model.py`, `model.mdl`, `model.xmile` для поддерживаемого subset;
- simulation job формирует `simulation.json`, `simulation.csv`;
- `GET /jobs/{id}/files/{filename}` допускает только whitelist новых артефактов;
- результаты generation/import/simulation имеют schema 2.0;
- старые model 1.0 принимаются simulation endpoint через migrator.

Idempotency import включает hash содержимого файла и options. Повтор того же ключа с другим файлом — conflict.

## 10. LLM generation 2.0

### 10.1 Pipeline

`brief → structure/topology → expressions → normalize → validation → graphs → exports`

1. **ModelBrief:** цель, границы, aggregation, горизонт, time unit, stocks, flows, exogenous inputs, ожидаемые loops и assumptions.
2. **Structure:** переменные, kinds, units, source/target flows, initial/constants.
3. **Expressions:** typed AST, а не Python.
4. **Normalize:** derivative из topology, canonical names, alias normalization без смены значений.
5. **Validation:** все уровни из раздела 7.
6. **Graphs:** детерминированные CLD/SFD.
7. **Exports:** trusted code generators.

`cld_data` и `sfd_data` больше не являются независимыми LLM outputs.

### 10.2 Structured output и repair

- Strict JSON Schema применяется на brief, variables, equations, chat и repair; Pydantic validation обязателен независимо от provider.
- Unstructured fallback не выполняется молча: доступен только через явный `*_ALLOW_UNSTRUCTURED_FALLBACK=1`.
- Repair получает текущий fragment и structured errors. Общий bounded budget по умолчанию — 3 попытки на run и покрывает malformed JSON, ранние schema/reference errors и semantic repairs.
- Unknown references в stock initial и expression IDs проверяются на variables/equations стадиях до полной сборки документа.
- Нет автоматического paid retry после окончательной semantic failure.
- Repair не может молча удалить ошибочный stock/flow, изменить units ради прохождения или заменить неизвестную функцию нулём.
- После repair обязательны полная повторная validation и smoke-симуляция готовой модели; repair-ответы сохраняются в workdir.

### 10.3 Pattern library

Встроенная versioned библиотека из 16 archetypes в core, не в продуктовой БД:

- exponential and logistic growth;
- teacup cooling;
- SIR и seasonal SIRS;
- predator–prey с явной conversion efficiency;
- Bass diffusion;
- inventory и backlog;
- workforce/aging chain;
- supply chain delay и supply chain bullwhip;
- renewable resource;
- student club с capacity, burnout и campaigns;
- Lorenz, Van der Pol и Duffing.

Каждый pattern содержит description, tags, canonical IR, units, topology, assumptions, expected qualitative behavior и numerical fixture. Подбор первой версии — deterministic по tags/keywords; embeddings добавляются только при измеримом выигрыше.

Нельзя копировать текущий fixture `predation` как приток predators без conversion efficiency в библиотеку «правильных» примеров.

### 10.4 Оценка качества

- Offline fixtures не выполняют сеть и полностью воспроизводимы.
- Отдельный benchmark: 26 описаний, 3 запуска на описание с фиксированными provider settings, симуляция полного горизонта.
- Behavior-oracles для repeated waves, bullwhip, campaign wave, chaotic sign changes, limit cycle и two-well switching дополняют finite/dynamic checks.
- Метрики: executable rate, semantic pass, units pass, topology pass, graph consistency, assumptions visibility, repair rate, latency, tokens/cost.
- Semantic pass оценивается по essential stocks/flows/topology/units и ожидаемому поведению, а не совпадению имён с единственным эталоном.
- Начальные release targets: executable ≥ 90%, semantic ≥ 85%, explicit assumptions = 100%, graph consistency = 100% среди принятых моделей. Это цели новой оценки, не утверждение о текущем качестве.
- Live OpenRouter smoke обязателен перед release, но не входит в обычный offline test suite. API keys и raw prompts не попадают в логи.

### 10.5 Зафиксированные контракты последующих расширений

Эти возможности не блокируют backend, но реализуются в уже описанном IR, а не через параллельные форматы.

**Subscripts:**

- `dimensions` содержит именованные наборы string element ids; переменная декларирует `subscripts` как ссылки на dimensions.
- Scalar и array operations используют согласованные coordinates; запрещено неявное positional broadcasting несовместимых dimensions.
- Aggregation (`sum`, `prod`, `vmin`, `vmax`) явно перечисляет сокращаемые dimensions.
- Результат может быть canonical nested series либо deterministic flattened columns `variable[element,...]`; выбор задаётся параметром `flatten_output`.
- Subranges, subscript mapping и агрегации по выбранным элементам включаются только со своими golden tests.

**External series и сценарии:**

- `input_series` содержит sorted unique finite timestamps и finite values для разрешённых exogenous constants.
- Первая версия использует linear interpolation; поведение вне диапазона — `clamp | error`, по умолчанию `error`.
- Series нельзя использовать для подмены stock, flow или вычисляемого auxiliary.
- `Scenario` — named immutable набор constant overrides, stock initial overrides и input series поверх одного `model_hash`.
- Batch scenario job сохраняет каждый запуск отдельно и возвращает comparison manifest с общими variables/time grid; лимит по умолчанию — 50 сценариев.
- REST добавляет `POST /api/v1/scenario-runs`; CLI — `scenarios.py --model ... --scenarios ...`; это новый job kind, не скрытая группа независимых задач без общего статуса.

**Sensitivity / Monte Carlo:**

- Конфигурация содержит explicit seed, число runs, distributions и sampling targets.
- Первые distributions: `uniform`, `normal`, `lognormal`, `discrete`; параметры и bounds обязательны.
- Каждый sample сохраняется вместе с seed/config hash, чтобы запуск был воспроизводим.
- Summary содержит mean, std и заданные quantiles по времени/variables; сырые runs могут быть отдельными файлами с лимитами размера.
- Некорректный run не исчезает из статистики незаметно: failures имеют count, reasons и явную политику `fail_fast | keep_partial`.

**Calibration:**

- Вход — canonical model, CSV/JSON observations, соответствие observed columns переменным и bounded fit parameters.
- Первая цель — weighted least squares; явно задаются weights, initial values и method settings.
- Результат содержит fitted values, residual time series, RMSE/MAE, convergence и reproducible simulation config.
- Калибровка не изменяет исходную модель: создаётся новый model revision с provenance и отдельным hash.
- Восстановление topology/flow equations по наблюдениям является отдельным исследовательским режимом и не выдаётся за parameter calibration.

## 11. Миграция ModelDocument 1.0

1. Прочитать variables/equations, сохранить description, created_at и исходные labels.
2. Разобрать `integ(net_flow, initial)` в stock initial/derivative.
3. Преобразовать безопасный RHS в typed AST; `python_code` игнорировать и создать заново.
4. Сохранить нули без старого postprocess.
5. Восстановить flow endpoints по знакам references в stock derivative; пометить их `migration/inferred`.
6. При неоднозначной topology сохранить derivative и выдать warning; не угадывать SFD.
7. Разобрать известные units через alias registry; неизвестные сохранить как `null + units_raw`.
8. Провести validation и выдать найденные старые scientific issues как warnings/errors, не исправляя их молча.
9. Результат всегда сериализовать как 2.0; версию generator/migrator записать в provenance.

Текущий predator–prey fixture сохраняется как characterization input, но эталонный fixture должен быть исправлен явно: predator births отделяются от prey predation и связаны conversion efficiency.

## 12. Надёжность и безопасность сервиса

- `SERV_WORKER_CONCURRENCY` реально управляет semaphore; сейчас значение захардкожено и должно быть исправлено.
- Generation/simulation/import имеют отдельные configurable timeouts.
- Subprocess получает CPU, address-space/memory, output-size и file-count limits; превышение даёт sanitised resource error.
- Контейнер worker запускается non-root, с drop capabilities, no-new-privileges, read-only FS кроме workdir, CPU/memory/PIDs limits на уровне Compose.
- При timeout завершается вся process group, без оставшихся дочерних процессов.
- Каждый job имеет isolated workdir, atomic artifacts и bounded logs/results.
- Watchdog отмечает stale pending/running jobs как error с `STALE_JOB`; автоматически не повторяет потенциально платную генерацию.
- Retry создаёт новый attempt, сохраняет предыдущие logs и не нарушает idempotency history.
- Model variables, time series, AST size, table size и output points имеют лимиты до начала дорогих вычислений.
- Внутренние пути, секреты, raw provider response и stack traces не попадают в публичную ошибку.

## 13. Артефакты и наблюдаемость

Manifest содержит:

- schema/generator/parser versions;
- model/source hashes;
- stages и durations;
- LLM provider/model, attempts, usage/cost при наличии, без prompts/keys;
- assumptions/warnings/capabilities summary;
- requested/actual engine/method/time grid;
- output files, sizes и checksums;
- validation status и безопасный error summary.

Structured logs содержат `job_id`, `attempt`, `stage`, `duration`, `engine`, `method`, `fallback`, `validation_status`. По job ID должна быть видна причина выбора fallback и фактический численный метод.

## 14. Тестовая стратегия

### 14.1 Baseline и characterization

До изменений зафиксировать текущие defects как regression cases:

- zero stock превращается в 100 — после исправления должен остаться нулём;
- PySD Euler при запросе RK45 — после исправления метод должен совпадать с фактическим;
- SciPy RK4≠RK45;
- `time_step=0.3` на `[0,1]` — явный grid error, не другая сетка;
- fallback обязан вернуть flows/auxiliaries/constants;
- CLD/SFD invalid cases не должны получать `valid=true` из-за отфильтрованных warnings.

### 14.2 Scientific golden suite

| Модель | Проверка |
|---|---|
| Exponential growth | Analytic solution; Euler/RK4/adaptive; все series |
| Logistic growth | Analytic solution и carrying capacity |
| Teacup | Analytic cooling; units |
| SIR | Нулевой Recovered; сохранение S+I+R |
| Predator–prey | Conversion efficiency; qualitative cycles; units |
| Inventory/backlog | Nonnegative policy/bounds; topology |
| Workforce | Lookup, MIN, hiring/maturation/departure |
| Rössler | Coupled ODE и reference trajectory |
| Delay/smooth | Golden output PySD/Vensim semantics |
| Events/lookups | Boundary times, interpolation/extrapolation |

Дополнительно: auxiliary cycle, incompatible units, flow without stock, derivative/topology mismatch, unknown lookup, zero denominators, NaN/Inf, unsupported functions, excessive AST/grid/file size.

### 14.3 Contract и integration tests

- CLI generate/simulate/import/export без backend.
- REST 202 → polling → result/files для всех job kinds.
- Model 1.0 migration и 2.0 round-trip.
- Vensim/XMILE import → simulation → export → reimport с численным сравнением.
- Идемпотентность, retry, stale watchdog, timeout/resource limit, worker restart, две параллельные задачи.
- Невозможность исполнить malicious equation, uploaded Python, XML external entity и path traversal.
- Для forced fallback requested/actual method совпадают.
- Ни один success test не проверяет только initial values/finite numbers: обязательны numerical/semantic assertions.

### 14.4 Стандартные проверки

```bash
uv run pytest
uv run ruff check .
```

Дополнительно перед release: Docker E2E для generate/import/simulate, реальный OpenRouter benchmark с ограниченным бюджетом и numerical capability report.

## 15. Этапы и Definition of Done

### Этап 0. Baseline

- Зафиксировать defects regression tests и текущий behavior report.
- Сформировать scientific corpus и источники golden outputs.
- Выпустить JSON Schema черновик IR 2.0/capability matrix.

**DoD:** defects воспроизводятся тестами; corpus имеет проверяемые эталоны; не приняты непроверенные golden values.

### Этап 1. Scientific hardening

- IR 2.0/migration, explicit assumptions, удаление эвристик.
- Units/topology/AST/DAG validation.
- Исправление engine/method/grid/all-series.
- Детерминированные CLD/SFD.
- Resource limits/watchdog.

**DoD:** scientific unit tests и CLI regression зелёные; zero SIR корректен; методы и сетка соответствуют metadata; все variables возвращаются; некорректные topology/units не проходят как `done`.

### Этап 2. SD language и interoperability

- Conditional/events/lookups/delay/smooth/initial.
- Vensim/XMILE import/export и CSV.
- Capability-aware engine routing.
- Docker/API integration новых job kinds.

**DoD:** golden suite для новых функций зелёный; round-trips не теряют semantics; unsupported features явно отклоняются; REST/CLI выдают эквивалентные результаты.

**Backend gate:** после этапов 0–2 IR, simulation и artifacts стабильны; backend может использовать их без последующей ломающей миграции ради базовых возможностей.

### Этап 3. LLM quality

- ModelBrief, patterns, structured output, bounded repair.
- Offline benchmark и live OpenRouter evaluation.

**DoD:** опубликованы измеренные metrics; достигнуты п. 10.4 targets либо release сознательно не допускается; нет скрытых assumptions и graph inconsistencies.

### Этап 4. Advanced analysis

- Subscripts, external series, scenarios, seeded sensitivity, calibration.
- Каждая возможность включается отдельно через capabilities, без изменения базового IR semantics.

**DoD каждой возможности:** отдельные numerical tests, resource limits, CLI/REST contracts и regression suite.

## 16. Сквозная приёмка

1. SIR с нулевым Recovered сохраняет население и не получает искусственных 100.
2. Неизвестный коэффициент либо требует ввода, либо явно виден как assumption.
3. Euler, RK4 и adaptive methods выполняются именно указанным способом; metadata не врёт.
4. При одинаковых условиях PySD/SciPy на общем subset согласуются в допусках.
5. Все variable series доступны после любого successful simulation.
6. Некратная сетка, неправильные units, dangling flow и auxiliary cycle дают понятную ошибку.
7. Lookup/event/delay/smooth проходят golden tests; unsupported capability не эмулируется неправильно.
8. Vensim и XMILE можно импортировать, запустить и экспортировать без пользовательского Python.
9. CLD/SFD соответствуют AST/topology; отсутствие loop само по себе не портит модель.
10. CLI и REST проходят одинаковые scientific cases; все стандартные lint/test/Docker проверки зелёные.
11. Worker timeout/restart не оставляет бесконечный running job и не создаёт скрытый duplicate paid generation.
12. Live OpenRouter quality задокументирован отдельно от offline fixture success.

## 17. Риски

| Риск | Решение |
|---|---|
| PySD и SciPy расходятся в stateful semantics | Ограничить SciPy compatible subset; capability errors вместо fallback |
| Полный Vensim/XMILE слишком велик | Declared subset, capability matrix, corpus-driven расширение |
| IR станет избыточным/противоречивым | Единый AST, derivative/topology consistency, derived artifacts only |
| Размерный анализ блокирует старые модели | Unknown units с warning; strict mode для generated models |
| Delay/events чувствительны к timestep | Fixed semantics и boundary golden tests |
| LLM repair увеличивает стоимость | Жёсткие attempt/token budgets, нет blind retries |
| Миграция сохранит старые scientific errors | Provenance + warnings/errors, никаких скрытых исправлений |
| Большие модели исчерпывают память | Предварительные limits, process isolation, streaming/chunking в advanced этапе |

## 18. Источники

- Текущие contracts/pipeline: `pipeline/schemas.py`, `pipeline/generation.py`, `pipeline/expressions.py`.
- Graphs/codegen: `pipeline/graphs.py`, `pipeline/codegen.py`.
- Simulation: `pipeline/simulation/engine.py`, `pipeline/simulation/scipy_runner.py`.
- Legacy behavior: `../sdcloud_old/code/backend/app/utils/model_postprocess.py`, `services/generation`, `services/simulation`.
- [Оригинальный sdCloud](https://sdcloud.io/).
- [История проекта у Veesp](https://veesp.com/blog/sdcloud/).
- [sdCloud: Cloud-based computation environment, 2016](https://proceedings.systemdynamics.org/2016/proceed/papers/P1164.pdf).
- [Cloud execution architecture, 2018](https://ceur-ws.org/Vol-2344/paper4.pdf).
- [Adaptation of SD execution algorithms, 2018](https://www.fruct.org/files/publications/volume-22/fruct22/Mul.pdf).
- [Automated Modelization of Dynamic Systems, 2018](https://www.fruct.org/files/publications/volume-23/acm23/Per.pdf).
- [Original-project test-model corpus](https://github.com/alexprey/test-models).

## 19. Состояние реализации

- Реализованы этапы 0–4 и hardening 0.2.0: ModelDocument 2.0, scientific hardening, SD language, Vensim/XMILE interoperability, ModelBrief, 16 validated patterns, DSL normalization, strict output, ранний bounded repair, subscripts, external series, scenarios, sensitivity analysis и calibration.
- Offline suite: 96 passed; Ruff: All checks passed.
- Docker E2E подтверждён для generation/simulation/import, scenarios, sensitivity, calibration, subscripts и external series.
- Live OpenRouter baseline predator–prey на финальном коде: 0 repairs, 10 variables, 41 simulation point, все значения конечные. Live SIRS с остаточным `R₀ < 1` после bounded repairs был отклонён semantic validation; это не засчитывается как успешная генерация.
- Полный benchmark 26 описаний × 3 запуска не выполнялся; runner и corpus доступны в `benchmark.py` и `pipeline/benchmark_prompts.json`.
- Subscripts поддерживаются в canonical IR и PySD/Vensim, включая 1D/2D arrays, indexed references и aggregation. SciPy для subscripts отклоняется capability error.
- Subscripted XMILE export и subscripted import не заявлены как поддерживаемые и возвращают явный unsupported error; базовые scalar Vensim/XMILE round-trips работают.
- Backend и frontend реализованы; границы модулей сохранены.

## 20. Локальный inference 0.2.0

- `pipeline/llm.py` поддерживает `openrouter`, `fixture` и `local`/`vllm`/`openai_compatible` через OpenAI-compatible `/chat/completions`.
- Local provider требует `LOCAL_LLM_MODEL`, использует `LOCAL_LLM_BASE_URL` и не требует API key. Таймаут, max tokens, structured output и явный unstructured fallback настраиваются через `LOCAL_LLM_*`.
- `docker-compose.local-llm.yml` добавляет vLLM и направляет gen-api/gen-worker только на него. По умолчанию используется `QuantTrio/Qwen3-VL-30B-A3B-Instruct-AWQ`, max model len 16384 и GPU memory utilization 0.92.
- Целевое окружение — NVIDIA GPU с 24 GB VRAM и NVIDIA Container Toolkit. Для другого OpenAI-compatible сервера отдельный vLLM container не обязателен.
- Первая загрузка весов требует сети или подготовленного Hugging Face cache; после загрузки внешние LLM API не используются и облачный fallback отсутствует.
- На RTX 5090 Laptop 24 GB под WSL2 подтверждены `/v1/models`, CLI generate/simulate, REST generation/simulation и полный продуктовый сценарий. Полный benchmark 26×3 завершён; метрики и недостигнутые targets зафиксированы ниже.

## 21. Live hardening 0.2.1

- Final repair продолжается после malformed response в пределах общего budget; `null` не стирает прежние equations, failed cases сохраняют repair count. Kind-specific strict schema требует ненулевой stock initial.
- Generation-нормализация без `eval` и без изменения численной семантики: явные units нулевых literals, numeric folding, `dimensionless → {}`, удаление derivative при flow topology и `constant → auxiliary` при динамике. Импортированные модели не затрагиваются.
- Smoke выполняется на полном горизонте и входит в repair loop. Валидаторы units/topology не ослаблены ради benchmark pass-rate.
- CLI predator-prey: 22,6 с, 0 repairs, 10 variables, 41 finite point. REST teacup: 14,1 с, 0 repairs, 21 finite point. Продуктовый чат создал две версии, ответил на вопрос, запустил simulation и Python export.
- Pattern selection покрыт classification golden suite: все 26 описаний выбирают ожидаемый archetype. Полный local benchmark 26×3: 78 cases, executable 83,3%, semantic 83,3%, behavior 75,6%, average 31,256 с. Все 26 описаний имеют хотя бы один semantic success; 14 имеют behavior success во всех трёх запусках. Bullwhip 3/3, student club 2/3.
- Quality targets 90/85/85% не достигнуты. Остаточные классы: malformed JSON/DSL, unknown references и units, статические supply-delay модели, превышение 16K context в одном repair. Validators не ослаблялись. Offline suite: 104 tests; Ruff зелёный.
