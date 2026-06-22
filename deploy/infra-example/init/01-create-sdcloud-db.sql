-- ──────────────────────────────────────────────────────────────
-- Инициализация БД и пользователя для проекта sdCloud
--
-- Куда копировать:
--   ~/infra/postgres/init/01-create-sdcloud-db.sql
--   (на пользователе admin, где крутится shared PostgreSQL)
--
-- PostgreSQL выполняет скрипты из /docker-entrypoint-initdb.d только
-- при первом запуске контейнера, если директория данных ещё пуста.
--
-- ВАЖНО: замените 'change-me-strong-password' на реальный пароль
-- и пропишите его в backend/.env проекта sdcloud:
--   DATABASE_URL=postgresql+asyncpg://sdcloud:change-me-strong-password@shared-postgres:5432/sdcloud
-- ──────────────────────────────────────────────────────────────

-- Создаём пользователя с правами на подключение и создание объектов в своей БД
CREATE USER sdcloud
  WITH PASSWORD 'change-me-strong-password'
  NOSUPERUSER
  NOCREATEDB
  NOCREATEROLE
  CONNECTION LIMIT 100;

-- Создаём базу данных с владельцем sdcloud
CREATE DATABASE sdcloud
  OWNER sdcloud
  ENCODING 'UTF8'
  LC_COLLATE = 'en_US.utf8'
  LC_CTYPE = 'en_US.utf8'
  TEMPLATE template0;

-- Подключаемся к базе sdcloud для настройки привилегий на схему public
\c sdcloud;

-- Даём полный доступ к схеме public
GRANT ALL PRIVILEGES ON SCHEMA public TO sdcloud;
ALTER SCHEMA public OWNER TO sdcloud;

-- Все будущие объекты в схеме public по умолчанию принадлежат sdcloud
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO sdcloud;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO sdcloud;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO sdcloud;
