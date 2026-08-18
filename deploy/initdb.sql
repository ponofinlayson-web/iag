-- Runs once on first boot of the postgres volume (docker-entrypoint-initdb.d).
-- Invoked by initdb.sh, which supplies the password as :'app_password'
-- (psql variable) -- there is no cleartext password in this file.
-- POSTGRES_USER=iag_migrate (superuser + DB owner, DDL authority) already
-- exists when this runs; we only add the least-privilege app role.
CREATE ROLE iag_app LOGIN PASSWORD :'app_password';
GRANT CONNECT ON DATABASE iag TO iag_app;
\c iag
GRANT USAGE ON SCHEMA public TO iag_app;
-- Tables created later by iag_migrate (alembic) auto-grant DML to iag_app:
ALTER DEFAULT PRIVILEGES FOR ROLE iag_migrate IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO iag_app;
ALTER DEFAULT PRIVILEGES FOR ROLE iag_migrate IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO iag_app;
