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
    {{"id": "population", "kind": "stock", "label": "Population", "description": "...", "units": {{"person": 1}}, "initial": {{"op": "lit", "value": 1000}}}},
    {{"id": "births", "kind": "flow", "label": "Births", "units": {{"person": 1, "year": -1}}, "source": {{"kind": "cloud", "id": "births_source"}}, "target": {{"kind": "stock", "id": "population"}}}},
    {{"id": "birth_rate", "kind": "constant", "label": "Birth rate", "units": {{"year": -1}}}}
  ],
  "tables": [],
  "assumptions": []
}}

Правила:
- kind: stock, flow, auxiliary, constant.
- id: ASCII snake_case; label человекочитаемый.
- units: base unit -> integer exponent; {{}} для dimensionless. Для flow: stock units / time unit.
- Для каждого stock укажи initial typed AST; ноль разрешён.
- Для каждого flow укажи source и target: stock или cloud, хотя бы один endpoint — stock.
- death/mortality/outflow: source=stock, target=cloud или другой stock. Birth/inflow: target=stock. Не направляй смерть из cloud в stock.
- Predator-prey обязательно содержит predation, зависящий от обеих популяций, и приток хищников, зависящий от predation или добычи.
- Разные сущности не преобразуются без conversion coefficient с правильными units.
- Неизвестные иллюстративные значения заноси в assumptions: path, value, source="llm_inferred", rationale, requires_confirmation.
- Не добавляй выражения на этой стадии.
"""

EQUATION_GENERATION_PROMPT = """\
Создай выражения для всех flow, auxiliary и constant системно-динамической модели.

Описание системы и текущий запрос на изменение:
{description}

ModelBrief:
{brief}

Структура:
{variables}

Верни ТОЛЬКО JSON-объект:
{{
  "expressions": {{
    "births": {{"op": "mul", "args": [{{"op": "ref", "name": "population"}}, {{"op": "ref", "name": "birth_rate"}}]}},
    "birth_rate": {{"op": "lit", "value": 0.02}}
  }}
}}

Typed AST:
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
step, pulse, pulse_train, ramp, delay1, delay3, smooth, smooth3, initial.

Правила:
- Ровно одно expression для каждой flow, auxiliary и constant, но не для stock.
- Используй только существующие variable ids и table ids.
- Сохраняй units: flow = stock / time unit.
- Constants не зависят от time или runtime variables.
- Не используй INTEG: derivatives вычисляются из topology.
- Не меняй структуру, topology, начальные значения и units.
- Нулевые values допустимы. Не используй Python, imports, lambda или произвольные функции.
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

Каждый stock содержит initial typed AST. Каждая flow/auxiliary/constant содержит expression typed AST. Каждая flow содержит source/target и units. Не используй производную stock: она вычисляется из topology.

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
