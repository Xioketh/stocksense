-- Creates the assistant's own database next to the API's, on the same server.
-- Postgres runs this automatically ONLY when the db volume is first created.
-- For an existing volume, run: make assistant-db  (safe to run again).
-- Postgres has no "CREATE DATABASE IF NOT EXISTS", so psql's \gexec runs the
-- CREATE only when the SELECT returns a row (= the database is missing).
SELECT 'CREATE DATABASE stocksense_assistant'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'stocksense_assistant')\gexec