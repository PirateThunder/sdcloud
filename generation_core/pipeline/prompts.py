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

VARIABLE_EXTRACTION_PROMPT = """\
Ты проектируешь структуру системно-динамической модели.

Описание:
{description}

ModelBrief:
{brief}

Проверенный pattern, используй его как смысловой ориентир:
{pattern}

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
