-- Runs once when the Postgres volume is first created. Schema is owned by Alembic (backend/alembic);
-- this only enables extensions the app may use.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
