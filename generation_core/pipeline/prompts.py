DIRECT_GENERATION_PROMPT = """\
По одному описанию создай полную системно-динамическую модель одним JSON-ответом.

Описание:
{description}

Верни ТОЛЬКО JSON-объект с полями name, time, variables, tables и assumptions.
time содержит unit, initial_time, final_time, time_step и saveper. Каждая переменная
имеет уникальный ASCII snake_case id и kind=stock|flow|auxiliary|constant.
Для stock задай initial как число или формулу. Для flow, auxiliary и constant задай
expression как число или DSL-формулу. Для flow задай source и target: stock или cloud;
хотя бы один endpoint должен быть stock. Для явного ОДУ можно задать stock.derivative,
но только если оно согласовано с flow topology. units — словарь base unit -> integer
exponent, {{}} для dimensionless; flow имеет units stock/time. Для неприменимых optional
полей передавай null, для subscripts — [].

DSL поддерживает числа, true/false, pi, e, time, variable ids, скобки, + - * / % ^,
сравнения, and/or, not и функции min, max, abs, exp, log, log10, sqrt, sin, cos, tan,
floor, ceil, round, power, xidz, zidz, if_then_else, step, pulse, pulse_train, ramp,
delay1, delay3, delay1i, delay3i, smooth, smooth3, smoothi, smooth3i, initial.
Это не Python: imports, lambda, атрибуты, индексы, присваивания и произвольные функции
запрещены. Для lookup используй lookup(table_id, expression).

Сохрани все явно заданные значения и уравнения. Fractional rate имеет units 1/time;
для dimensional threshold, time constant и conversion создавай named constant с units.
Не используй безразмерный literal для преобразования размерностей. Значения, которых
нет в описании, выбирай только при необходимости и перечисляй в assumptions с непустым
value, source="llm_inferred", rationale и requires_confirmation. Не добавляй assumptions
для явно заданных параметров. Не заменяй предметную область готовым шаблоном.
"""


MODEL_BRIEF_PROMPT = """\
Составь ModelBrief для системно-динамической модели по описанию.

Описание:
{description}

Проверенный ориентир (не копируй его, если он не подходит):
{pattern}

Верни ТОЛЬКО JSON:
{{
  "goal": "цель модели",
  "boundaries": ["что входит и что не входит в модель"],
  "time_horizon": "горизонт",
  "time_unit": "year",
  "aggregation": "medium",
  "stocks": ["ключевые накопления"],
  "flows": ["процессы изменения stocks"],
  "exogenous_inputs": ["внешние параметры"],
  "expected_feedback_loops": ["ожидаемые петли"]
}}

Не придумывай feedback обязательно. Для predator-prey явно перечисли predation и рост хищников за счёт добычи. Для эпидемии укажи переходы между stocks.
"""

COMPONENT_BRIEF_GUIDANCE = """\
Для новой модели вне проверенного pattern используй typed components, если они покрывают
механизмы системы. Builder сам построит variables, equations, units коэффициентов и topology.
Явные d(stock)/dt с поддерживаемыми DSL-выражениями преобразуй в polynomial_ode, включая
несколько связанных stocks и нелинейные terms; не возвращай components=[] из-за их сложности.
Запись min(stock/service_time,max_service) означает queue, а third-order material response —
delay, если заданы его параметры. Не используй имя d(stock)/dt как id переменной.
Не выдумывай новый kind. Если механизм не покрыт, верни components=[] для обычного pipeline.
Если components непустой, задай time={unit, initial_time, final_time, time_step, saveper};
возьми horizon и unit из запроса. Выбирай time_step не больше четверти самой маленькой
time constant. saveper должен быть целым кратным time_step, обычно равным ему; для более
чем 9999 внутренних шагов builder увеличит только saveper, сохраняя time_step.

Доступные механизмы:
- first_order: source stock передаёт target stock или cloud:<id>. Ровно один из coefficient
  (1/(source*time) с conversion при необходимости) и time_constant. Укажи initial_source,
  initial_target, source_units, target_units, time_unit. Не используй source=target.
- conditional_inflow: внешний rate поступает в stock с start_time до end_time; outflow —
  stock*elimination_rate. Подходит для infusion с последующей элиминацией. Укажи stock,
  inflow, outflow, rate, start_time, end_time, elimination_rate, initial, units, time_unit.
  Этот component уже задаёт обе скорости: не добавляй polynomial_ode или first_order outflow
  для того же stock.
- queue: arrivals добавляет arrival_rate, service=min(max(stock,0)/service_time,max_service).
  Для конечного входного потока задай arrival_start_time и arrival_end_time, иначе последний=null.
  Укажи stock, arrivals, service, service_time, max_service, arrival_rate, initial, units,
  time_unit. time_step не должен превышать service_time, иначе Euler может снять больше items,
  чем находится в очереди. Не добавляй отдельный first_order outflow, scheduled_flow или другую
  queue для того же процесса. Не создавай дополнительный serviced stock без явного требования
  пользователя.
  Для одной очереди не добавляй polynomial_ode со вторым representation того же backlog или
  отдельным удалением его items. Тернарный `condition ? a : b` не поддерживается: используй
  if_then_else или typed component.
- scheduled_flow: один внешний приток или расход, rate меняется на rate_after в change_time.
  Для такого переключения внешней скорости не используй polynomial_ode с if/min и не делай
  rate или change_time отдельными stocks. source/target — stock или cloud:<id>, хотя бы один
  stock; initial_source, initial_target, source_units и target_units одинаковы, time_unit задан.
  Для разряда source=stock, target=cloud:sink и оба rate неотрицательны.
  Для явно signed net flow в stock используй source=cloud:net_source, target=stock и сохраняй
  отрицательный rate без замены нулём или max. Не заменяй его двумя conditional_inflow с
  одинаковым stock.
- delay: третье транспортное запаздывание input_rate с delay_time и явным initial_delayed_rate;
  consumption_time задаёт последующий first-order расход, либо null для нулевого расхода.
  input_rate и input_rate_after — только числа из описания, не symbolic ids; rate_change_time
  задаёт изменение входа, иначе оба optional-поля null. Укажи stock, inflow, outflow,
  initial_stock, stock_units, time_unit. stock — единственный terminal accumulator, получающий
  delayed inflow и теряющий consumption; не создавай отдельные in_transit и terminal stocks,
  polynomial_ode для terminal consumption или scheduled_flow для входа delay. Third-order уже
  содержит три внутренние стадии: не разбивай один material response на несколько delay components.
- polynomial_ode: stock с initial, units, time_unit, terms и parameters. Каждый term содержит
  coefficient (число или id parameter), expression БЕЗ coefficient и без общего знака,
  sign=1|-1 и name. Например -4*position — coefficient=4, expression="position", sign=-1.
  Сумма terms задаёт derivative, не включай её в expression. Ссылки на coefficient внутри
  того же expression запрещены. Составляй несколько terms только для суммы верхнего уровня;
  сумму, умножаемую на общий coefficient, всегда сохраняй одним expression.
  Отрицательный вклад задавай как положительный coefficient и sign=-1, а не как отрицательный
  coefficient и sign=1: двойной отрицательный знак меняет направление процесса.
  parameters: id, value, role=rate|threshold|scale, units=null или base units. Для threshold
  без units builder возьмёт units текущего stock; scale без units — dimensionless; rate без
  units — 1/time, кроме coefficient, чьи units выводятся из stock/time - expression units.
  Для пороговых значений в выражении используй named threshold, не голый dimensional literal.
  Для dimensionless числового нормировщика (например /3) допустим числовой literal.

Все ids — ASCII snake_case, уникальные внутри модели. В каскаде первого порядка можно
повторить промежуточный stock только с теми же initial и units: builder объединит его.
Для каждого ODE stock создавай ровно один component и перечисляй все его terms внутри.
Другой stock никогда не является ComponentParameter: для d(position)/dt=velocity используй
coefficient=1, expression="velocity" и parameters=[]; не создавай parameter с id="velocity".
Для parameter.role допустимы только rate, threshold и scale, но не названия единиц или stocks.
Не копируй числа из этих правил: бери параметры из запроса. Для выбранных иллюстративных
значений добавь краткие assumptions с source="llm_inferred" и непустым value.

Примеры синтаксиса, не параметры для копирования:
first_order:
{{
  "kind": "first_order", "source": "source_stock", "target": "cloud:sink",
  "flow": "transfer", "coefficient": 0.2, "time_constant": null,
  "initial_source": 100, "initial_target": 0,
  "source_units": {{"item": 1}}, "target_units": null, "time_unit": "day"
}}
Для target=stock вместо target_units=null передай фактические units stock. Можно вместо
coefficient задать time_constant=5; не задавай оба, кроме взаимно обратных значений.

conditional_inflow:
{{
  "kind": "conditional_inflow", "stock": "amount", "inflow": "supply",
  "outflow": "elimination", "rate": 5, "start_time": 0, "end_time": 2,
  "elimination_rate": 0.1, "initial": 0, "units": {{"item": 1}},
  "time_unit": "minute"
}}

queue:
{{
  "kind": "queue", "stock": "backlog", "arrivals": "arrivals",
  "service": "service", "service_time": 0.5, "max_service": 10,
  "arrival_rate": 3, "initial": 20, "units": {{"item": 1}},
  "time_unit": "minute", "arrival_start_time": 0, "arrival_end_time": null
}}

scheduled_flow:
{{
  "kind": "scheduled_flow", "source": "inventory", "target": "cloud:consumption",
  "flow": "consumption", "rate": 2, "rate_after": 5, "change_time": 10,
  "initial_source": 100, "initial_target": 0,
  "source_units": {{"item": 1}}, "target_units": null, "time_unit": "day"
}}
Обязательно задай flow, rate, rate_after и change_time. Не добавляй отдельный запас для rate.

delay:
{{
  "kind": "delay", "stock": "inventory", "inflow": "transport",
  "outflow": "consumption", "input_rate": 8, "delay_time": 3,
  "initial_stock": 0, "initial_delayed_rate": 0,
  "stock_units": {{"item": 1}}, "time_unit": "day",
  "consumption_time": 2, "input_rate_after": 12, "rate_change_time": 6
}}
Delay уже включает delayed inflow и consumption: не добавляй scheduled_flow или first_order
для тех же процессов и не создавай отдельный stock для input_rate.

polynomial_ode (logistic growth и loss):
{{
  "kind": "polynomial_ode", "stock": "state", "initial": 10,
  "units": {{"state": 1}}, "time_unit": "time",
  "terms": [
    {{"coefficient": "growth_rate", "expression": "state * (1 - state / capacity)",
      "sign": 1, "name": "growth"}},
    {{"coefficient": 0.05, "expression": "state", "sign": -1, "name": "loss"}}
  ],
  "parameters": [
    {{"id": "growth_rate", "value": 0.2, "role": "rate", "units": null}},
    {{"id": "capacity", "value": 100, "role": "threshold", "units": null}}
  ]
}}
Для coefficient parameter оставляй units=null: builder выведет размерность. Для threshold
тоже можно null. Не сокращай выражение state*(driver-threshold) до state*driver: threshold
является частью динамики. Числа и знаки в expression не дублируй coefficient/sign.
Сохраняй КАЖДЫЙ численный множитель из уравнения: state^3/3 требует
expression="state^3/3" или coefficient=1/3. Если общий rate умножается на сумму, сохраняй
факторизованную форму одним term, не раскрывай скобки и не распределяй rate между terms:
{"coefficient": "outer_rate", "expression": "state + offset - damping * other_state",
 "sign": 1, "name": "recovery"}
с parameters outer_rate(role="rate", units=null), offset(role="threshold", units=null)
и damping(role="scale", units=null). Подставь фактические ids, values, states и знаки из запроса.
Не раскрывай такие скобки вообще. Если части одного parenthesized expression стали разными
terms, объедини их обратно в один term с общим outer coefficient. Это требование сохранения
семантики, а не только units: у inner coefficient нельзя терять outer multiplier. Перед возвратом
проверь каждый outer*inner продукт по исходному уравнению. Запись coefficient=outer_rate*inner_rate
не поддерживается: coefficient может быть только числом или id parameter. Не создавай parameter,
который не используется в coefficient или expression: builder отклонит декоративные параметры.
Не используй один named coefficient для слагаемых с разными units. Для additive constant
предпочитай числовой coefficient и expression="1" либо отдельный coefficient с units=null;
не переиспользуй rate из stock term, если additive constant требует stock/time.
Не удаляй state-фактор из multiplicative term: inner_rate*state нельзя заменять на inner_rate.
"""

COMPONENT_PLAN_PROMPT = """\
Выбери и задай параметры typed mechanisms для модели. Не пиши переменные, equations,
общие рассуждения или новый ModelBrief: только ComponentPlan JSON.

Описание системы:
{description}

Уже готовый ModelBrief:
{brief}

{component_guidance}

Верни ТОЛЬКО JSON:
{{
  "components": [],
  "time": null,
  "assumptions": []
}}

Для components непустого списка time обязателен. Численные значения из запроса копируй точно,
не заменяй их нулями, именами полей или placeholder-строками. units — только словарь
фактических единиц, например {{"person": 1}} или {{}}; никаких "unit", "base_unit",
"goal", "source" в качестве выдуманных размерностей. Для queue не дублируй delay или
first_order с теми же процессами. Для delay используй ровно один component, включая его
собственный consumption_time. Для spring position имеет derivative=velocity, а velocity —
заданное acceleration. Не добавляй assumptions для явно заданных параметров.
"""

VARIABLE_EXTRACTION_PROMPT = """\
Ты проектируешь структуру системно-динамической модели.

Описание:
{description}

ModelBrief:
{brief}

Проверенный pattern, используй его как смысловой ориентир:
{pattern}

{ode_guidance}

Верни ТОЛЬКО JSON-объект:
{{
  "name": "короткое имя модели",
  "time": {{"unit": "year", "initial_time": 0, "final_time": 100, "time_step": 0.25, "saveper": 0.25}},
  "variables": [
    {{"id": "population", "kind": "stock", "label": "Population", "description": "...", "units": {{"person": 1}}, "initial": 1000}},
    {{"id": "births", "kind": "flow", "label": "Births", "units": {{"person": 1, "year": -1}}, "source": {{"kind": "cloud", "id": "births_source"}}, "target": {{"kind": "stock", "id": "population"}}}},
    {{"id": "birth_rate", "kind": "constant", "label": "Birth rate", "units": {{"year": -1}}, "initial": 0.02}}
  ],
  "tables": [],
  "assumptions": []
}}

Правила:
- kind: stock, flow, auxiliary, constant.
- id: ASCII snake_case; label человекочитаемый.
- units: base unit -> integer exponent; {{}} для dimensionless. Для flow: stock units / time unit.
- Fractional growth/adoption/recommendation/mortality rate имеет units 1/time,
  а не person/time или recommendation/time. Если flow=stock*rate, units потока уже
  получается из stock/time; не используй stock вместо такого flow без rate.
- Голый числовой literal безразмерен. Для dimensional rate, time constant или threshold
  создавай именованную constant с корректными units и используй её id. Не используй
  безразмерное 1.0 как время или conversion coefficient.
- derivative stock имеет units stock/time: position/time — velocity, velocity/time —
  acceleration. Не путай acceleration и force без mass conversion. Derivative и flow
  topology должны быть согласованы, а не дублировать разные уравнения.
- Для каждого stock укажи initial как число или DSL-формулу, например 1000 или
  "total_population - initial_infectious". initial=null для stock ЗАПРЕЩЁН; ноль разрешён.
- Каждое накопление из ModelBrief.stocks должно иметь kind="stock", не constant и не flow.
- Для constant укажи initial как число или постоянную DSL-формулу; initial=null запрещён.
  Строка "lit" не является значением: передавай само число, например 100 или 0.02.
  Для неизвестного значения выбери разумную иллюстративную величину и добавь assumption.
- Для flow/auxiliary initial=null. expression для всех non-stock на этой стадии null.
- Для неприменимых derivative/source/target/bounds/units_raw ставь null;
  subscripts=[], allow_isolated=false, topology_status="declared", exogenous=false.
- Для каждого flow укажи source и target: stock или cloud, хотя бы один endpoint — stock.
- death/mortality/outflow: source=stock, target=cloud или другой stock. Birth/inflow: target=stock. Не направляй смерть из cloud в stock.
- Predator-prey обязательно содержит predation, зависящий от обеих популяций, и приток хищников, зависящий от predation или добычи.
- Для Bass diffusion используй стандартную структуру: stocks potential_adopters и adopters,
  один flow adoption от potential_adopters к adopters, constants total_market, innovation
  и imitation. innovation/imitation имеют units 1/time. Не разделяй adoption на отдельные
  advertising/recommendation flows и не вводи advertising budget в dollars без явной необходимости.
- Разные сущности не преобразуются без conversion coefficient с правильными units.
- Неизвестные иллюстративные значения заноси в assumptions: path, value, source="llm_inferred", rationale, requires_confirmation.
  Для каждой переменной не больше одной assumption. value — непустая строка с тем же
  числом или формулой, что initial. Не повторяй assumptions и не создавай их для
  подтверждённых pattern defaults: повторяющиеся блоки приводят к обрыву JSON.
- Не добавляй выражения переменных в свой JSON-ответ на этой стадии.
- Pattern содержит проверенные initial, units, time и справочные equations. Если пользователь
  не задал конкретные значения, сохрани эти illustrative defaults; не сокращай time.final_time
  и не увеличивай time_step. Для Lorenz, Van der Pol и Duffing без явных физических
  параметров используй нормированные ids, kinds, units и time.unit из pattern. Не выдумывай
  электрическую схему с C/L, volt/ampere или second вместо нормированного oscillator.
  Для seasonal SIRS сохрани immunity_duration=90 и base_contact_rate=0.35, если не заданы другие.
- Для predator-prey и renewable resource сохрани начальные conditions и fractional rates из
  pattern, если пользователь не задал свои. Не вычисляй точное равновесие и не делай
  regeneration равной harvest без явной просьбы смоделировать steady state/equilibrium.
- Изменяй структуру pattern только при явном требовании пользователя.
"""

EQUATION_GENERATION_PROMPT = """\
Создай выражения для всех flow, auxiliary и constant системно-динамической модели.

Описание системы и текущий запрос на изменение:
{description}

ModelBrief:
{brief}

Проверенный pattern со справочными equations:
{pattern}

Структура:
{variables}

Верни ТОЛЬКО JSON-объект. Предпочитай короткие формулы DSL и числа:
{{
  "expressions": [
    {{"id": "births", "expression": "population * birth_rate"}},
    {{"id": "birth_rate", "expression": 0.02}},
    {{"id": "seasonal_input", "expression": "sin(2 * pi * time / period)"}},
    {{"id": "demand", "expression": "if_then_else(time >= 10, high_demand, base_demand)"}}
  ]
}}

DSL поддерживает числа, true/false, pi, e, time, variable ids, скобки,
унарные +/-/not, операции + - * / % ^, сравнения, and/or и вызовы функций.
Для lookup используй lookup(table_id, expression). Это не Python: атрибуты,
imports, lambda, индексы, присваивания и произвольные функции запрещены.

Вместо DSL можно вернуть canonical typed AST:
- {{"op": "lit", "value": 0.1}}
- {{"op": "ref", "name": "population"}}
- {{"op": "time"}}
- {{"op": "neg"|"pos"|"not", "arg": EXPRESSION}}
- {{"op": "add"|"sub"|"mul"|"div"|"pow"|"mod", "args": [LEFT, RIGHT]}}
- {{"op": "lt"|"le"|"gt"|"ge"|"eq"|"ne", "args": [LEFT, RIGHT]}}
- {{"op": "and"|"or", "args": [CONDITION, CONDITION]}}
- {{"op": "if", "condition": CONDITION, "then": EXPRESSION, "otherwise": EXPRESSION}}
- {{"op": "call", "name": "function", "args": [EXPRESSION]}}
- {{"op": "lookup", "table": "table_id", "arg": EXPRESSION}}

Разрешённые call functions:
min, max, minimum, maximum, abs, exp, log, log10, sqrt, sin, cos, tan,
floor, ceil, round, power, xidz, zidz, if_then_else,
step, pulse, pulse_train, ramp, delay1, delay3, delay1i, delay3i,
smooth, smooth3, smoothi, smooth3i, initial.
Для delay/smooth третий аргумент initial value необязателен. При его наличии можно
использовать delay3i(order_rate, delay_time, initial_value) и smooth3i аналогично.

Правила:
- Ровно одно expression для каждой flow, auxiliary и constant, но не для stock.
- Используй только существующие variable ids и table ids.
- Сохраняй units: flow = stock / time unit.
- Аргументы min/max должны иметь одинаковые units. Для sales используй demand или
  min(demand, inventory / adjustment_time), но не min(inventory, demand):
  stock нельзя сравнивать со stock/time без деления на время.
- Constants не зависят от time или runtime variables.
- Для Bass diffusion используй единый flow:
  adoption = potential_adopters * (innovation + imitation * adopters / total_market).
  innovation и imitation имеют units 1/time. Это учитывает оба канала без отдельного
  денежного advertising budget и без потери potential_adopters из уравнения.
- Для constant повтори initial из структуры без изменений. Никогда не используй
  expression="same_constant_id" для constant: это цикл, а не числовое значение.
- Не используй INTEG: derivatives вычисляются из topology.
- Не меняй структуру, topology, начальные значения и units.
- Нулевые values допустимы. Не используй Python, imports, lambda или произвольные функции.
"""

BRIEF_REPAIR_PROMPT = """\
Ответ стадии brief не прошёл проверку. Исправь его, не начинай другую модель.

Ошибка:
{error}

Исходное задание:
{original_prompt}

Прежний ответ:
{response}

Верни ТОЛЬКО один JSON-ОБЪЕКТ верхнего уровня, НЕ массив и не список boundaries.
Сохрани предметную область и заполни все обязательные поля:
{{
  "goal": "цель модели",
  "boundaries": ["границы модели"],
  "time_horizon": "горизонт",
  "time_unit": "year",
  "aggregation": "medium",
  "stocks": ["ключевые накопления"],
  "flows": ["процессы изменения stocks"],
  "exogenous_inputs": ["внешние параметры"],
  "expected_feedback_loops": ["ожидаемые петли"]
}}
"""

STAGE_REPAIR_PROMPT = """\
Ответ стадии {stage} не прошёл проверку. Исправь ответ, а не начинай другую модель.

Ошибка:
{error}

Исходное задание стадии:
{original_prompt}

Предыдущий ответ:
{response}

Верни ТОЛЬКО исправленный JSON для той же стадии и в том же формате.
Сохрани корректные переменные, ids, topology, units и ModelBrief. Не добавляй
произвольный код или новые сущности без необходимости. Для equations используй
только существующие variable ids; разрешены DSL-формулы из исходного задания
или canonical typed AST. Не повторяй malformed JSON, op с именем функции вместо
op="call", числовые assumption.value или expressions для несуществующих ids.
Для stock initial всегда передавай число или формулу, а не null. Голое "lit" —
не число и не формула. Значение нельзя переносить в rationale или assumptions
вместо initial. Вызывай функции напрямую,
например min(a, b), без обёртки call(...).
Для ComponentPlan поля input_rate, input_rate_after, rate и другие numeric parameters
должны быть JSON-числами из описания, а не symbolic variable ids. Delay уже включает
входное расписание, delayed inflow и consumption: не добавляй scheduled_flow или first_order
для тех же процессов. При duplicate ids удали дублирующий механизм вместо случайного
переименования stocks и flows; source/target scheduled_flow должны быть stock или cloud:<id>.
Если ответ оборван или повторяет assumptions, верни полный компактный JSON той же модели:
одна assumption на переменную, непустое value, никаких повторяющихся блоков.
"""

REPAIR_PROMPT = """\
Исправь системно-динамическую модель по структурированным ошибкам валидатора.

ModelBrief:
{brief}

Проверенный pattern:
{pattern}

Ошибки:
{errors}

Текущая модель:
{document}

Верни ТОЛЬКО JSON-объект с полной исправленной структурой:
{{
  "name": "имя",
  "time": {{"unit": "year", "initial_time": 0, "final_time": 100, "time_step": 0.25, "saveper": 0.25}},
  "variables": [],
  "tables": [],
  "assumptions": []
}}

Каждый stock содержит initial, каждая flow/auxiliary/constant содержит expression.
Для initial/expression разрешены DSL-формулы, числа или canonical typed AST.
Каждая flow содержит source/target и units. Не используй производную stock: она вычисляется из topology.

Специальные исправления:
- Не опускай существующие variables и не превращай stocks/constants/auxiliaries в flows.
  При ошибках только units сохраняй kinds и source/target, меняя equations или добавляя
  conversion coefficients. Если topology-ошибка показывает, что constant ошибочно стал
  stock endpoint, верни kind="constant" и исправь соответствующий endpoint на cloud.
- DERIVATIVE_TOPOLOGY_MISMATCH: удали derivative stock (null), сохранив flows и их topology.
- DYNAMIC_CONSTANT: переменная, зависящая от time или runtime variables, должна быть auxiliary, а не constant.
- INVALID_FLOW при source=target: interest/growth/income обычно поступает из cloud в stock; расход уходит из stock в cloud. Endpoints не должны совпадать.
- Если в conditional branches одна ветка — нулевой literal, а другая имеет units, запиши ноль как 0 * другая_ветка, например 0 * recruitment. Аналогично для min/max.
- При INCOMPATIBLE_UNITS в min/max сравнивай величины одинаковой размерности:
  sales = demand или min(demand, inventory / adjustment_time), не min(inventory, demand).
  Для bullwhip pattern используй sales=demand: не добавляй незапрошенный stockout limit,
  inventory / 1.0 или новые коэффициенты вместо проверенного уравнения.
- Не исправляй units молчаливой сменой declared units: сначала исправь formula, conversion coefficients и flow topology.
- Если неправильна units самого коэффициента, исправь именно её, а не units stock/flow.
  Fractional growth/adoption/recommendation/mortality rate имеет units 1/time, без
  дополнительных person или recommendation. Значение коэффициента при этом сохрани.
  При делении stock на время используй именованную константу с units времени, например
  adjustment_time. Не используй голый literal 1.0: если константы нет, добавь её с
  корректными initial/units и assumption, сохранив остальную структуру.
- Для Lorenz/Van der Pol/Duffing используй equations pattern без сокращения размерных
  коэффициентов: например decay_y и xy_rate нельзя опускать. Без явных физических
  параметров сохраняй нормированные ids, kinds, units и time.unit, а не физическую схему.
- При INCOMPATIBLE_UNITS рассчитай dimensions каждого сомножителя. Для advertising_budget
  в dollars и adoption в person/time нужен явный коэффициент person/(dollar*time);
  для ad_spend_rate в dollars/time — person/dollar, без ещё одного деления на время.
  Не используй безразмерный числовой множитель для преобразования валюты в людей.
  Для Bass diffusion сохрани potential_adopters
  в обоих adoption flows; в recommendations используй potential_adopters * adopters *
  imitation / total_market, где imitation имеет units 1/time.
- При SMOKE_SIMULATION/non-finite исправь уравнения или уменьши time_step и saveper; не сокращай final_time и не скрывай ошибку.
- Если supply-delay модель статична, используй проверенный order_rate из pattern, если id
  совпадает: `100 + step(50, 5)`. Не вычитай inventory без target и не используй голое
  `1.0` вместо adjustment_time с units времени. Delay-функцию сохрани.
- Первый аргумент delay/smooth должен уже иметь units скорости потока. Для пополнения используй delay3(order_rate, lead_time) или (target_inventory - inventory) / lead_time, а не разность stocks внутри delay.
- Аргумент sin/cos должен быть dimensionless: делить time нужно на константу period с units времени. Base demand и amplitude должны иметь units потока.
- Вызывай min/max и другие функции напрямую, без обёртки call(...).

Исправь именно указанные ошибки, сохрани корректные части и ModelBrief. Не удаляй predation и другие существенные процессы только ради прохождения валидации. Death/outflow исходит из stock, birth/inflow направлен в stock. Не назначай произвольные ненулевые коэффициенты. Не добавляй Python или другие поля.
"""

CONVERSATION_PROMPT = """\
Ты — AI-ассистент по системной динамике sdCloud. Определи, как обработать текущее сообщение пользователя в контексте беседы.

История (последние сообщения, текущего сообщения здесь ещё нет):
{history}

Текущая canonical model или null:
{base_model}

Текущее сообщение:
{description}

Выбери ровно одно действие:
- answer: пользователь задаёт вопрос, просит объяснение, интерпретацию, сравнение или ведёт обычную беседу. Ответь содержательно, используя историю и model JSON, если она есть. Не утверждай, что изменил модель или запустил симуляцию.
- clarify: намерение изменить или создать модель есть, но запрос слишком неоднозначен для корректного действия. Задай один конкретный уточняющий вопрос и при необходимости предложи варианты.
- generate: пользователь просит создать новую модель и текущей модели нет.
- update: текущая модель есть и пользователь просит добавить, удалить или изменить переменные, связи, уравнения, параметры, начальные значения, горизонт либо другую часть модели.

Правила:
- Вопрос о модели — НЕ update. Update только при явной просьбе изменить модель.
- Короткие уточнения вроде "сделай 0.2", "добавь уход через год" или "а если убрать лис" относятся к update, если модель есть.
- Не требуй повторять описание системы, если смысл понятен из истории и текущей модели.
- Если модели нет, update не разрешён. Если модель есть, используй update вместо generate, пока пользователь явно не просит начать другую модель в этом же чате.
- Отвечай на языке пользователя. Для answer дай полный ответ сразу; не возвращай только намерение.
- assistant_text обязателен для всех действий. Для generate/update напиши короткое сообщение, которое можно показать после успешной генерации.

Верни ТОЛЬКО JSON:
{{"action": "answer|clarify|generate|update", "assistant_text": "текст ответа"}}
"""
