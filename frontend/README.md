# frontend

Браузерный интерфейс sdCloud: лендинг, вход по email/OTP и рабочее пространство
для контекстного чата, просмотра моделей, CLD/SFD, уравнений и симуляций.
Обращается только к backend через same-origin `/api/*`.

Версия — **0.3.0**. Запуск всего продукта — [корневой README](../README.md).

## Возможности

- Адаптивный лендинг и интерфейс входа по одноразовому email-коду.
- Создание, переименование и удаление бесед; история сообщений.
- Ответы ассистента, уточнения и создание новых версий модели в контексте чата.
- Библиотека моделей и неизменяемых версий.
- Таблица переменных, assumptions, warnings и читаемые LaTeX-формулы через KaTeX.
- CLD/SFD на React Flow.
- Настройка параметров и integration method, запуск симуляций и история запусков.
- Интерактивные графики Recharts, выбор переменных и экспорт CSV.
- Экспорт Python/Vensim/XMILE при поддержке конкретной моделью.
- Светлая/тёмная тема, состояния загрузки и ошибок.

## Стек

- Next.js 16 App Router, React 19, TypeScript strict.
- Bun 1.3 как package manager; production Docker build использует Node.js 22.
- Feature-Sliced Design (`src/fsd`).
- Tailwind CSS 4, Base UI, Lucide.
- TanStack Query, Zustand, ky, Zod.
- React Flow, Recharts, KaTeX, react-markdown.
- Vitest + Testing Library, Playwright, Biome.

## Маршруты

| Путь | Назначение |
|---|---|
| `/` | Лендинг |
| `/login` | Email/OTP-вход |
| `/chat` | Новая беседа |
| `/chat/{id}` | История и контекстная работа с моделью |
| `/models` | Библиотека моделей |
| `/models/{id}` | Версии модели |
| `/model-versions/{id}` | Уравнения, диаграммы, код и симуляции версии |

Все рабочие маршруты защищены auth gate. Access token хранится в памяти, а не в
localStorage; после перезагрузки сессия восстанавливается через HttpOnly refresh
cookie. При ответе `401` выполняется одна попытка refresh перед повтором запроса.

## Локальная разработка

Требуются Bun и запущенный backend. Из `frontend/`:

```bash
bun install --frozen-lockfile
bun run dev --port 56556
```

Откройте **http://127.0.0.1:56556**. По умолчанию `/api/:path*` перенаправляется на
`http://localhost:61231`. Для другого адреса:

```bash
BACKEND_URL=http://127.0.0.1:61231 bun run dev --port 56556
```

Переменные:

| Переменная | Назначение |
|---|---|
| `BACKEND_URL` | Адрес backend для Next.js rewrites |
| `NEXT_PUBLIC_LLM_PROVIDER` | Отображаемый режим LLM (`fixture`, `openrouter` или `local`) |
| `PORT` | Порт production/dev-сервера, если он не передан флагом |
| `FRONTEND_URL` | Base URL для Playwright; по умолчанию `http://127.0.0.1:56556` |

`NEXT_PUBLIC_*` запекается в клиентский bundle при сборке. Не передавайте через него
секреты. В Docker `BACKEND_URL=http://back-api:61230` задаётся build argument;
внешний backend host-порт внутри сети не используется.

## Проверки качества

```bash
bun run lint
bunx tsc --noEmit
bun run test
bun run build
```

Браузерные E2E:

```bash
# Один раз, если Chromium ещё не установлен.
PLAYWRIGHT_BROWSERS_PATH=0 bunx playwright install chromium

# Нужны работающие backend + generation_core с локальным OTP.
bun run build
bun run test:e2e
```

Playwright повторно использует сервер на `127.0.0.1:56556` либо запускает
`bun run start --port 56556`. Для production-сборки перед повторным E2E после
изменений снова выполните `bun run build`.

Скрипты npm: `dev`, `build`, `start`, `lint`, `format`, `test`, `test:e2e`.
Команда `bun run format` изменяет файлы и применяется только для намеренного
форматирования.

## Структура FSD

```text
src/
  app/                    Next.js routes и layouts
  fsd/
    app/                  Providers, root shell и глобальные стили
    pages/                Страницы и композиция экранов
    widgets/              App chrome и sidebar бесед
    features/             Auth, chat, simulation, theme
    entities/             Conversation, generation, model, session, simulation
    shared/
      api/                HTTP-клиент, refresh и downloads
      lib/                Общие утилиты
      ui/                 Базовые UI-компоненты и KaTeX
public/                   Статические ассеты
tests/                    Vitest unit/component tests
e2e/                      Playwright-сценарии
```

Направление зависимостей: `app → pages → widgets → features → entities → shared`.
Не добавляйте обратные импорты из нижних слоёв в верхние. Предметные HTTP-запросы
находятся в entities/features, а не разбросаны по визуальным компонентам.

## Docker

Из корня репозитория:

```bash
docker compose up --build -d frontend
```

Контейнер собирает приложение, запускает его от непривилегированного пользователя и
публикует внутренний порт `54733` на `127.0.0.1:${FRONTEND_HOST_PORT:-56556}`.
После изменения кода или `NEXT_PUBLIC_*` необходима пересборка образа.
