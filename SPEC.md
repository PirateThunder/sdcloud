# sdCloud — Спецификация проекта

## Общее описание
sdCloud — AI-ассистент для автоматической генерации системно-динамических моделей из текстовых описаний. Пользователь вводит описание системы на естественном языке, LLM анализирует текст, генерирует системно-динамическую модель (переменные, уравнения, CLD/SFD), PySD выполняет симуляцию, а результат (модель + графики) возвращается пользователю в чат-интерфейсе.

## Архитектура системы

### Backend (Python, FastAPI)
```
sdcloud/backend/
├── app/
│   ├── __init__.py
│   ├── main.py                    # Точка входа FastAPI
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py              # Pydantic Settings (env vars)
│   │   ├── security.py            # JWT, password hashing
│   │   ├── exceptions.py          # Кастомные исключения
│   │   └── dependencies.py        # FastAPI dependencies (get_db, get_current_user)
│   ├── db/
│   │   ├── __init__.py
│   │   ├── session.py             # SQLAlchemy AsyncSession + engine
│   │   └── base.py                # DeclarativeBase
│   ├── models/
│   │   ├── __init__.py
│   │   ├── user.py                # User model
│   │   ├── conversation.py        # Conversation model
│   │   ├── message.py             # Message model (user + assistant)
│   │   ├── generated_model.py     # Generated SD model
│   │   └── simulation.py          # Simulation run
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── user.py                # User schemas (create, read, update)
│   │   ├── conversation.py        # Conversation schemas
│   │   ├── message.py             # Message schemas
│   │   ├── generated_model.py     # Generated model schemas
│   │   └── simulation.py          # Simulation schemas
│   ├── api/
│   │   ├── __init__.py
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── router.py          # Главный v1 router
│   │       └── endpoints/
│   │           ├── __init__.py
│   │           ├── auth.py        # Регистрация, логин, JWT refresh
│   │           ├── conversations.py # CRUD бесед + сообщений
│   │           ├── generate.py    # Генерация моделей (async через Taskiq)
│   │           ├── models.py      # CRUD сгенерированных моделей
│   │           ├── simulate.py    # Запуск симуляции PySD
│   │           └── health.py      # Health check
│   ├── services/
│   │   ├── __init__.py
│   │   ├── llm/
│   │   │   ├── __init__.py
│   │   │   └── openrouter.py      # Адаптация UniversalAI для async
│   │   ├── simulation/
│   │   │   ├── __init__.py
│   │   │   ├── pysd_runner.py     # Запуск PySD симуляций
│   │   │   └── vensim_export.py   # Экспорт в Vensim .mdl
│   │   └── graph/
│   │       ├── __init__.py
│   │       ├── validator.py       # Валидация графов (networkx)
│   │       ├── cld_builder.py     # Построение CLD
│   │       └── sfd_builder.py     # Построение SFD
│   ├── utils/
│   │   ├── __init__.py
│   │   └── sd_prompts.py          # Prompts для LLM (few-shot SD examples)
│   └── workers/
│       ├── __init__.py
│       └── tasks.py               # Taskiq задачи (async generation)
├── migrations/                    # Alembic миграции
├── tests/
├── alembic.ini
├── pyproject.toml
├── requirements.txt
└── Dockerfile
```

### Frontend (Next.js + FSD)
```
sdcloud/frontend/
├── src/
│   ├── app/                       # Next.js App Router
│   │   ├── layout.tsx             # Корневой layout
│   │   ├── page.tsx               # Главная страница (редирект на /chat)
│   │   ├── globals.css            # Глобальные стили
│   │   ├── chat/
│   │   │   └── page.tsx           # Страница чата
│   │   ├── login/
│   │   │   └── page.tsx           # Страница входа
│   │   └── register/
│   │       └── page.tsx           # Страница регистрации
│   ├── entities/                  # Бизнес-сущности
│   │   ├── user/
│   │   │   ├── model.ts           # Типы User
│   │   │   └── api.ts             # API пользователя
│   │   ├── chat/
│   │   │   ├── model.ts           # Типы Chat, Message
│   │   │   └── api.ts             # API чатов
│   │   ├── model/
│   │   │   ├── model.ts           # Типы GeneratedModel
│   │   │   └── api.ts             # API моделей
│   │   └── simulation/
│   │       ├── model.ts           # Типы Simulation
│   │       └── api.ts             # API симуляций
│   ├── features/                  # Фичи (user interactions)
│   │   ├── auth/
│   │   │   ├── ui/
│   │   │   │   ├── LoginForm.tsx
│   │   │   │   └── RegisterForm.tsx
│   │   │   ├── model.ts
│   │   │   └── api.ts
│   │   ├── chat-send/
│   │   │   ├── ui/
│   │   │   │   ├── ChatInput.tsx
│   │   │   │   └── MessageList.tsx
│   │   │   ├── model.ts
│   │   │   └── api.ts
│   │   ├── model-view/
│   │   │   ├── ui/
│   │   │   │   ├── CLDViewer.tsx   # Визуализация CLD
│   │   │   │   ├── SFDViewer.tsx   # Визуализация SFD
│   │   │   │   └── EquationsView.tsx
│   │   │   ├── model.ts
│   │   │   └── api.ts
│   │   └── simulation-run/
│   │       ├── ui/
│   │       │   ├── SimulationChart.tsx
│   │       │   └── RunButton.tsx
│   │       ├── model.ts
│   │       └── api.ts
│   ├── widgets/                   # Композиционные виджеты
│   │   ├── chat-layout/
│   │   │   └── ui/
│   │   │       └── ChatLayout.tsx
│   │   ├── sidebar/
│   │   │   └── ui/
│   │   │       └── ChatSidebar.tsx
│   │   └── header/
│   │       └── ui/
│   │           └── AppHeader.tsx
│   ├── shared/                    # Переиспользуемое
│   │   ├── api/
│   │   │   ├── client.ts          # ky instance (прямые запросы к бэку)
│   │   │   └── query-client.ts    # TanStack Query client
│   │   ├── config/
│   │   │   └── index.ts           # API_BASE_URL и другие константы
│   │   ├── types/
│   │   │   └── index.ts           # Общие типы
│   │   ├── lib/
│   │   │   └── utils.ts           # Хелперы
│   │   └── ui/                    # Переиспользуемые shadcn компоненты
│   └── pages/                     # Legacy pages (если нужно)
├── public/
├── components.json                # shadcn config
├── next.config.js
├── tailwind.config.ts
├── tsconfig.json
└── package.json
```

## API Endpoints

### Auth
- `POST /api/v1/auth/register` — Регистрация
- `POST /api/v1/auth/login` — Логин (JWT)
- `POST /api/v1/auth/refresh` — Refresh token
- `GET /api/v1/auth/me` — Текущий пользователь

### Conversations
- `GET /api/v1/conversations` — Список бесед
- `POST /api/v1/conversations` — Создать беседу
- `GET /api/v1/conversations/{id}` — Получить беседу с сообщениями
- `DELETE /api/v1/conversations/{id}` — Удалить беседу

### Messages
- `POST /api/v1/conversations/{id}/messages` — Отправить сообщение
- `GET /api/v1/conversations/{id}/messages` — История сообщений
- `POST /api/v1/conversations/{id}/messages/stream` — WebSocket стриминг

### Generation
- `POST /api/v1/generate` — Запустить генерацию модели (async через Taskiq)
- `GET /api/v1/generate/{task_id}/status` — Статус генерации
- `GET /api/v1/generate/{task_id}/result` — Результат генерации

### Models
- `GET /api/v1/models` — Список сгенерированных моделей
- `GET /api/v1/models/{id}` — Получить модель
- `PUT /api/v1/models/{id}` — Обновить модель
- `DELETE /api/v1/models/{id}` — Удалить модель
- `POST /api/v1/models/{id}/export` — Экспорт в Vensim

### Simulation
- `POST /api/v1/simulate` — Запустить симуляцию PySD
- `GET /api/v1/simulate/{id}` — Получить результаты симуляции

## Модели данных

### User
```python
class User:
    id: UUID (PK)
    email: str (unique)
    username: str (unique)
    hashed_password: str
    is_active: bool = True
    created_at: datetime
    updated_at: datetime
```

### Conversation
```python
class Conversation:
    id: UUID (PK)
    user_id: UUID (FK)
    title: str
    system_prompt: str | None
    model_type: str = "system_dynamics"  # sd, abm, des
    created_at: datetime
    updated_at: datetime
```

### Message
```python
class Message:
    id: UUID (PK)
    conversation_id: UUID (FK)
    role: str  # "user" | "assistant" | "system"
    content: str
    model_metadata: dict | None  # generated model data
    tokens_used: int | None
    created_at: datetime
```

### GeneratedModel
```python
class GeneratedModel:
    id: UUID (PK)
    message_id: UUID (FK)
    conversation_id: UUID (FK)
    name: str
    variables: list[dict]  # stocks, flows, auxiliaries
    equations: list[dict]
    cld_data: dict  # nodes + edges для визуализации
    sfd_data: dict  # nodes + edges для визуализации
    vensim_code: str | None
    python_code: str | None
    status: str  # "pending" | "generating" | "completed" | "error"
    created_at: datetime
```

### Simulation
```python
class Simulation:
    id: UUID (PK)
    model_id: UUID (FK)
    parameters: dict
    time_start: float
    time_end: float
    time_step: float
    results: dict  # time series data
    status: str  # "pending" | "running" | "completed" | "error"
    created_at: datetime
    completed_at: datetime | None
```

## Процесс генерации модели (Pipeline)

1. **Получение запроса**: Пользователь отправляет текстовое описание системы
2. **Извлечение переменных**: LLM анализирует текст, выделяет stocks, flows, auxiliaries
3. **Построение CLD**: Генерация причинно-следственной диаграммы (nodes + edges)
4. **Валидация графа**: Проверка через networkx (циклы, связность)
5. **Построение SFD**: Генерация диаграммы потоков (stocks + flows + converters)
6. **Генерация уравнений**: Математические уравнения для каждого элемента
7. **Создание Python модели**: Генерация кода для PySD
8. **Симуляция**: Запуск через PySD, получение временных рядов
9. **Возврат результата**: Модель + графики + уравнения пользователю

## Технологии

### Backend
- Python 3.12
- FastAPI (async)
- SQLAlchemy 2.0 (async)
- Alembic (миграции)
- PostgreSQL 16
- Redis (кэш + Taskiq брокер)
- Taskiq (async задачи)
- httpx (async HTTP для OpenRouter)
- PySD (симуляция)
- networkx (валидация графов)
- JWT (python-jose)
- passlib (хеширование паролей)
- pytest (тесты)

### Frontend
- Bun
- Next.js 15 (App Router)
- TypeScript
- shadcn/ui
- Tailwind CSS
- ky (HTTP клиент)
- TanStack Query (React Query)
- Zustand (состояние)
- react-markdown
- recharts (графики)
- react-flow (визуализация графов CLD/SFD)

## Конфигурация окружения (.env)
```
# Server
PORT=54101

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:58749/sdcloud

# Redis
REDIS_URL=redis://localhost:59293/1

# JWT
SECRET_KEY=your-secret-key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# OpenRouter
OPENROUTER_API_KEY=your-api-key
OPENROUTER_MODEL=openrouter/google/gemma-4-31b-it:free

# CORS
BACKEND_CORS_ORIGINS=http://localhost:56555

# API URL для фронта
NEXT_PUBLIC_API_URL=http://localhost:54101
```

## Интеграция с OpenRouter
Адаптировать класс `UniversalAI` из `main10.py`:
- Убрать прокси (socks5)
- Сделать async версию с `httpx.AsyncClient`
- Упростить до текстового чата (без image/audio/video)
- Интегрировать few-shot prompting для SD
