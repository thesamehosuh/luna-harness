-- Honcho database bootstrap. Runs once, on the first initialisation of the postgres volume
-- (docker-entrypoint-initdb.d). Honcho's own migrations create its tables; this only enables the
-- pgvector extension those migrations depend on (the image is pgvector/pgvector:pg15).
CREATE EXTENSION IF NOT EXISTS vector;
