# sdCloud

**sdCloud** — веб-платформа для генерации системно-динамических (System Dynamics) моделей из текстовых описаний с помощью больших языковых моделей (LLM) и их интерактивного моделирования.

Пользователь вводит описание системы на естественном языке, например:
> «Модель хищник–жертва: кролики размножаются, лисы едят кроликов».

После этого приложение:
1. Извлекает переменные (stocks, flows, auxiliaries).
2. Строит причинно-следственную диаграмму (CLD).
3. Генерирует уравнения и диаграмму потоков (SFD).
4. Создаёт Python-код модели.
5. Запускает симуляцию.
6. Возвращает пользователю модель, графики и уравнения в чат-интерфейсе.

---

## Стек технологий

### Backend
- **Python 3.12**
- **FastAPI** — асинхронный API
- **SQLAlchemy 2.0 + asyncpg** — работа с PostgreSQL
- **Alembic** — миграции базы данных
- **Redis** — кэш / брокер задач
- **Taskiq** — фоновые задачи (в текущей версии не активно)
- **litellm + OpenRouter** — запросы к LLM
- **PySD 3.14.3** — основной движок системно-динамической симуляции
- **SciPy (`solve_ivp`)** — fallback-режим симуляции, если PySD недоступен
- **JWT (python-jose) + passlib** — аутентификация
- **pytest** — тесты

### Frontend
- **Bun** — package manager / runtime
- **Next.js 15 (App Router)**
- **React 19 + TypeScript**
- **Tailwind CSS + shadcn/ui**
- **ky** — HTTP-клиент
- **TanStack Query** — серверное состояние
- **Zustand** — клиентское состояние (включая гостевой режим)
- **react-markdown** — рендеринг сообщений
- **recharts** — графики симуляций
- **@xyflow/react** — визуализация CLD/SFD

### Инфраструктура
- **Docker + Docker Compose**
- **PostgreSQL 16** — может использоваться несколькими проектами через отдельные базы
- **Redis 7** — может использоваться несколькими проектами через отдельные DB index
- **Nginx Proxy Manager** — обратный прокси и SSL

> **Философия инфраструктуры**: PostgreSQL и Redis поднимаются **один раз** как shared-сервисы (например, пользователем `admin` или в отдельном `deploy/infra-example/`). Каждый проект (sdcloud, project2, ...) подключается к ним через Docker-сеть `shared_network` и использует свою базу / Redis DB. Это экономит ресурсы и упрощает управление.

---

## Структура проекта

```
sdcloud/
├── backend/                 # FastAPI backend
│   ├── app/
│   │   ├── main.py          # Точка входа FastAPI
│   │   ├── core/            # config, security, CORS, exceptions
│   │   ├── db/              # SQLAlchemy engine, session, base
│   │   ├── models/          # SQLAlchemy-модели (User, Conversation, ...)
│   │   ├── schemas/         # Pydantic-схемы
│   │   ├── api/v1/endpoints/# Роуты: auth, conversations, generate, simulate
│   │   ├── services/        # LLM, симуляция, графы, экспорт
│   │   │   ├── generation/  # pipeline, python_generator
│   │   │   ├── simulation/  # pysd_runner, scipy_runner
│   │   │   └── graph/       # cld_builder, sfd_builder
│   │   └── workers/         # Taskiq-задачи (заготовка)
│   ├── alembic/             # Миграции
│   ├── tests/               # Тесты
│   ├── Dockerfile
│   ├── .env                 # Секреты (не коммитится)
│   └── .env.example
├── frontend/                # Next.js frontend
│   ├── src/
│   │   ├── app/             # Next.js App Router
│   │   ├── entities/        # Бизнес-сущности (user, chat, model, simulation)
│   │   ├── features/        # Фичи: auth, chat-send, model-view, simulation-run
│   │   ├── widgets/         # Композиционные виджеты
│   │   ├── shared/          # API-клиент, конфиг, UI-компоненты
│   │   └── app/             # Страницы
│   ├── Dockerfile
│   ├── .env.local           # Frontend env (не коммитится)
│   └── .env.example
├── deploy/
│   └── infra-example/       # Примеры shared-инфраструктуры
│       ├── docker-compose.yaml            # Production (NPM + PostgreSQL + Redis)
│       ├── docker-compose.local.yaml      # Shared PostgreSQL/Redis для локальной разработки
│       └── init/                          # SQL-скрипты инициализации БД
├── docker-compose.yaml                  # Production compose (backend + frontend)
├── docker-compose.local.yaml            # Local dev compose (backend + frontend + PostgreSQL + Redis)
├── docker-compose.local.shared.yaml     # Local dev compose (backend + frontend, shared PostgreSQL/Redis)
├── SPEC.md                              # Архитектурная спецификация
└── README.md                            # Этот файл
```

---

## Функциональность

- 🔐 Регистрация и вход по JWT
- 💬 Чат с LLM для создания моделей
- 👤 Гостевой режим — генерация моделей без регистрации (история хранится только в браузере)
- 📊 Автоматическая генерация:
  - списка переменных,
  - причинно-следственной диаграммы (CLD),
  - уравнений,
  - диаграммы потоков (SFD),
  - Python-кода модели.
- 🚀 Симуляция через PySD или SciPy fallback
- 📥 Экспорт модели в формат Vensim (.mdl)
- 🌐 Два публичных домена: фронтенд на `sdcloud.piratethunder.space`, API на `api.sdcloud.piratethunder.space`

---

## Локальный запуск

### 1. Подготовка окружения

```bash
# Клонируем/переходим в проект
cd sdcloud

# Копируем примеры переменных окружения
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local

# Добавляем реальный OPENROUTER_API_KEY в backend/.env
# Пример:
# OPENROUTER_API_KEY=sk-or-v1-...
```

> `backend/.env` и `frontend/.env.local` уже добавлены в `.gitignore` и не попадут в git.

### Вариант A: Self-contained стек (всё в одном compose)

Подходит для быстрого старта без настройки shared-инфраструктуры. PostgreSQL и Redis поднимаются внутри этого же compose-файла и доступны только этому проекту.

```bash
docker compose -f docker-compose.local.yaml --env-file backend/.env up -d --build
```

После сборки:
- **Frontend**: http://localhost:56555
- **Backend API**: http://localhost:54101
- **Swagger UI**: http://localhost:54101/docs
- **ReDoc**: http://localhost:54101/redoc

#### Локальные порты (self-contained)

| Сервис | Внутренний порт | Host-порт | Примечание |
|---|---|---|---|
| Backend | `54101` | `54101` | Случайный high-range порт |
| Frontend | `56555` | `56555` | Случайный high-range порт |
| PostgreSQL | `5432` | `58749` | Случайный high-range порт |
| Redis | `6379` | `59293` | Случайный high-range порт |

#### Остановка self-contained стека

```bash
# Остановить
docker compose -f docker-compose.local.yaml down

# Остановить и удалить тома (полная очистка БД/Redis)
docker compose -f docker-compose.local.yaml down -v
```

### Вариант B: Shared инфраструктура (рекомендуется)

PostgreSQL и Redis поднимаются **один раз** отдельно, а sdcloud подключается к ним. Это позволяет запускать рядом другие проекты (project2 и т.д.), использующие те же контейнеры, но свои базы / Redis DB.

#### Шаг 1. Поднять shared PostgreSQL и Redis

```bash
docker compose -f deploy/infra-example/docker-compose.local.yaml up -d
```

Это создаст Docker-сеть `shared_network` и контейнеры:
- `shared-postgres` (доступен на `localhost:58749`)
- `shared-redis` (доступен на `localhost:59293`)

> Для каждого нового проекта создавайте отдельную базу и пользователя через скрипты в `deploy/infra-example/init/`, либо вручную.

#### Шаг 2. Обновить `.env` для работы с shared-инфраструктурой

В `backend/.env` раскомментируйте локальные shared-значения:

```env
PORT=54101
DATABASE_URL=postgresql+asyncpg://sdcloud:sdcloud@shared-postgres:5432/sdcloud
REDIS_URL=redis://shared-redis:6379/1
FRONTEND_URL=http://localhost:56555
CORS_ORIGINS=http://localhost:56555,http://localhost:5173
```

#### Шаг 3. Запустить sdcloud

```bash
docker compose -f docker-compose.local.shared.yaml --env-file backend/.env up -d --build
```

После сборки:
- **Frontend**: http://localhost:56555
- **Backend API**: http://localhost:54101
- **Swagger UI**: http://localhost:54101/docs

#### Остановка sdcloud (shared-режим)

```bash
docker compose -f docker-compose.local.shared.yaml down
```

Shared PostgreSQL/Redis при этом продолжают работать и могут использоваться другими проектами.

---

## Shared PostgreSQL/Redis: как это работает

### Вопрос: могут ли другие проекты стучаться в PostgreSQL/Redis из `docker-compose.local.yaml`?

**Краткий ответ:** в текущей self-contained конфигурации (`docker-compose.local.yaml`) — нет, не в «чистом» виде.

**Почему:** в `docker-compose.local.yaml` PostgreSQL и Redis живут внутри приватной Docker-сети `sdcloud-network`, которая принадлежит только этому compose-проекту. Host-порты (`58749`, `59293`) привязаны к `127.0.0.1`, то есть доступны только с самого хоста. Другие Docker-контейнеры не могут подключиться к `127.0.0.1` хоста напрямую (кроме режима `host`), и не видят контейнеры sdcloud по имени, потому что находятся в другой сети.

### Как сделать общий доступ

1. Поднимите PostgreSQL/Redis через `deploy/infra-example/docker-compose.local.yaml` (или production-версию на пользователе `admin`). Эти контейнеры создают/используют сеть `shared_network`.
2. Все проекты, которым нужен доступ, подключаются к `shared_network` и обращаются по именам контейнеров:
   - `shared-postgres:5432`
   - `shared-redis:6379`
3. Каждый проект использует **свою базу** в PostgreSQL и **свой Redis DB index** (например, `/1` для sdcloud, `/2` для project2).

### Пример docker-compose для project2

```yaml
services:
  backend:
    image: project2-backend
    container_name: project2-backend
    networks:
      - shared_network
    environment:
      DATABASE_URL: postgresql+asyncpg://project2:pass@shared-postgres:5432/project2
      REDIS_URL: redis://shared-redis:6379/2

networks:
  shared_network:
    external: true
```

---

## Production-развёртывание

Архитектура production:

- **Пользователь `admin`** (или отдельный инфра-пользователь):
  - запускает Nginx Proxy Manager, общий PostgreSQL и общий Redis;
  - все сервисы подключены к Docker-сети `shared_network`;
  - единственные открытые наружу порты: `80`, `443` и панель NPM `81`.
- **Пользователь `sdcloud`**:
  - запускает только `backend` и `frontend`;
  - контейнеры подключены к `shared_network`;
  - публичные порты **не открываются**;
  - Nginx Proxy Manager проксирует запросы по именам контейнеров.

### DNS

Создайте A-записи, указывающие на IP сервера:

```
sdcloud.piratethunder.space     → <SERVER_IP>
api.sdcloud.piratethunder.space → <SERVER_IP>
```

### Подготовка shared-инфраструктуры (пользователь admin)

1. Создайте сеть (один раз):

   ```bash
   docker network create shared_network
   ```

2. Подготовьте общий PostgreSQL и Redis. Справочный пример см. в `deploy/infra-example/docker-compose.yaml`.

3. Создайте базу и пользователя для sdCloud:

   ```bash
   # Пример скрипта инициализации:
   # deploy/infra-example/init/01-create-sdcloud-db.sql
   ```

4. В Nginx Proxy Manager добавьте два Proxy Host:

   | Domain | Scheme | Forward Hostname | Forward Port |
   |---|---|---|---|
   | `sdcloud.piratethunder.space` | `http` | `sdcloud-frontend` | `56555` |
   | `api.sdcloud.piratethunder.space` | `http` | `sdcloud-backend` | `54101` |

5. В настройках каждого хоста включите **SSL** → Request a new SSL certificate → Accept Terms.

### Настройка переменных окружения (пользователь sdcloud)

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
```

`backend/.env` (production):

```env
PORT=54101
DATABASE_URL=postgresql+asyncpg://sdcloud:STRONG_PASSWORD@shared-postgres:5432/sdcloud
REDIS_URL=redis://shared-redis:6379/1
FRONTEND_URL=https://sdcloud.piratethunder.space
CORS_ORIGINS=https://sdcloud.piratethunder.space
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=openrouter/google/gemma-4-31b-it:free
SECRET_KEY=change-this-to-a-random-secret-key-in-production
```

`frontend/.env.local` (production):

```env
NEXT_PUBLIC_API_URL=https://api.sdcloud.piratethunder.space
```

> `NEXT_PUBLIC_API_URL` «запекается» в клиентский бандл на этапе сборки, поэтому его значение должно быть публичным API-доменом.

### Запуск production

```bash
docker compose -f docker-compose.yaml --env-file backend/.env up -d --build
```

Проверка:

- `https://sdcloud.piratethunder.space` — фронтенд
- `https://api.sdcloud.piratethunder.space/docs` — Swagger

### Остановка production

```bash
docker compose -f docker-compose.yaml down
```

---

## Справочник переменных окружения

### Backend (`backend/.env`)

| Переменная | Описание | Пример локально | Пример production |
|---|---|---|---|
| `PORT` | Порт, на котором слушает FastAPI внутри контейнера | `54101` | `54101` |
| `DATABASE_URL` | PostgreSQL DSN (asyncpg) | self-contained: `postgresql+asyncpg://sdcloud:sdcloud@localhost:58749/sdcloud`<br>shared: `postgresql+asyncpg://sdcloud:sdcloud@shared-postgres:5432/sdcloud` | `postgresql+asyncpg://sdcloud:pass@shared-postgres:5432/sdcloud` |
| `REDIS_URL` | Redis URL | self-contained: `redis://localhost:59293/1`<br>shared: `redis://shared-redis:6379/1` | `redis://shared-redis:6379/1` |
| `SECRET_KEY` | Ключ для JWT | `change-me` | `сильная-случайная-строка` |
| `ALGORITHM` | Алгоритм JWT | `HS256` | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Время жизни access-токена | `30` | `30` |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Время жизни refresh-токена | `7` | `7` |
| `FRONTEND_URL` | URL фронтенда для CORS/редиректов | `http://localhost:56555` | `https://sdcloud.piratethunder.space` |
| `CORS_ORIGINS` | Разрешённые origins | `http://localhost:56555,http://localhost:5173` | `https://sdcloud.piratethunder.space` |
| `OPENROUTER_API_KEY` | API-ключ OpenRouter | `sk-or-v1-...` | `sk-or-v1-...` |
| `OPENROUTER_MODEL` | ID модели | `openrouter/google/gemma-4-31b-it:free` | `openrouter/google/gemma-4-31b-it:free` |

### Frontend (`frontend/.env.local`)

| Переменная | Описание | Пример локально | Пример production |
|---|---|---|---|
| `NEXT_PUBLIC_API_URL` | Публичный URL backend API | `http://localhost:54101` | `https://api.sdcloud.piratethunder.space` |

---

## Полезные команды

```bash
# ── Self-contained локальный запуск ──
docker compose -f docker-compose.local.yaml --env-file backend/.env up -d --build

# ── Shared local запуск ──
docker compose -f deploy/infra-example/docker-compose.local.yaml up -d
docker compose -f docker-compose.local.shared.yaml --env-file backend/.env up -d --build

# ── Production запуск ──
docker compose -f docker-compose.yaml --env-file backend/.env up -d --build

# ── Логи ──
docker compose -f docker-compose.local.yaml logs -f backend
docker compose -f docker-compose.local.yaml logs -f frontend
docker compose -f docker-compose.local.shared.yaml logs -f backend

# ── Миграции вручную ──
docker compose -f docker-compose.local.yaml exec backend alembic upgrade head
# или в shared-режиме:
docker compose -f docker-compose.local.shared.yaml exec backend alembic upgrade head

# ── Зайти в контейнер backend ──
docker compose -f docker-compose.local.yaml exec backend bash

# ── Зайти в PostgreSQL (self-contained) ──
docker compose -f docker-compose.local.yaml exec postgres psql -U sdcloud -d sdcloud

# ── Зайти в shared PostgreSQL ──
docker compose -f deploy/infra-example/docker-compose.local.yaml exec postgres psql -U admin

# ── Остановить и удалить локальные volumes ──
docker compose -f docker-compose.local.yaml down -v
```

---

## Примечания

- В текущей версии генерация Python-кода модели выполняется **детерминированным генератором** (`backend/app/services/generation/python_generator.py`) на основе структурированных уравнений, а не LLM. Это исключает ошибки импортов и неопределённых переменных.
- Если PySD не может запустить модель, автоматически используется **SciPy fallback** (`backend/app/services/simulation/scipy_runner.py`).
- Мультиагентная система и fine-tuning в текущей версии **отложены** — для стабильной работы на бесплатных моделях OpenRouter их реализация ненадёжна. План описан в `kimi-agent-plans.md`.
- Redis DB index `1` выбран для изоляции от других проектов, использующих shared Redis.
- В production PostgreSQL/Redis не входят в `docker-compose.yaml` — они развёртываются как shared-инфраструктура и доступны через `shared_network`.

---

## Лицензия

Проект разрабатывается в приватном репозитории. Лицензия не определена.
