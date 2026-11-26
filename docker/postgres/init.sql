SELECT format('CREATE ROLE %I LOGIN', r)
FROM unnest(ARRAY[:'dlt_user', :'dbt_user', :'dg_user', :'agent_user', :'app_user', :'app_owner_user', :'mlflow_user']) AS r
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = r)\gexec

ALTER ROLE :"dlt_user"       PASSWORD :'dlt_pw';
ALTER ROLE :"dbt_user"       PASSWORD :'dbt_pw';
ALTER ROLE :"dg_user"        PASSWORD :'dg_pw';
ALTER ROLE :"agent_user"     PASSWORD :'agent_pw';
ALTER ROLE :"app_user"       PASSWORD :'app_pw';
ALTER ROLE :"app_owner_user" PASSWORD :'app_owner_pw';

ALTER ROLE :"agent_user" SET default_transaction_read_only = on;
ALTER ROLE :"agent_user" SET statement_timeout = '30s';  
ALTER ROLE :"dg_user"    SET search_path = dagster;    

ALTER ROLE :"mlflow_user" PASSWORD :'mlflow_pw';
ALTER ROLE :"mlflow_user" SET search_path = mlflow;

REVOKE ALL ON DATABASE :"db_name" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"db_name" TO :"dlt_user", :"dbt_user", :"dg_user", :"agent_user", :"app_user", :"app_owner_user";
GRANT CREATE  ON DATABASE :"db_name" TO :"dlt_user", :"dbt_user";
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

CREATE SCHEMA IF NOT EXISTS raw          AUTHORIZATION :"dlt_user";
CREATE SCHEMA IF NOT EXISTS raw_staging  AUTHORIZATION :"dlt_user";
CREATE SCHEMA IF NOT EXISTS staging      AUTHORIZATION :"dbt_user";
CREATE SCHEMA IF NOT EXISTS intermediate AUTHORIZATION :"dbt_user";
CREATE SCHEMA IF NOT EXISTS marts        AUTHORIZATION :"dbt_user";
CREATE SCHEMA IF NOT EXISTS reference    AUTHORIZATION :"dbt_user";
CREATE SCHEMA IF NOT EXISTS dagster      AUTHORIZATION :"dg_user";
CREATE SCHEMA IF NOT EXISTS app          AUTHORIZATION :"app_owner_user";

GRANT USAGE ON SCHEMA raw TO :"dbt_user";
GRANT SELECT ON ALL TABLES IN SCHEMA raw TO :"dbt_user";
ALTER DEFAULT PRIVILEGES FOR ROLE :"dlt_user" IN SCHEMA raw GRANT SELECT ON TABLES TO :"dbt_user";

GRANT USAGE ON SCHEMA staging, intermediate, marts, reference TO :"agent_user", :"app_user";

GRANT USAGE ON SCHEMA app TO :"app_user";
ALTER DEFAULT PRIVILEGES FOR ROLE :"app_owner_user" IN SCHEMA app
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app_user";
ALTER DEFAULT PRIVILEGES FOR ROLE :"app_owner_user" IN SCHEMA app
    GRANT USAGE, SELECT ON SEQUENCES TO :"app_user";


GRANT CONNECT ON DATABASE :"db_name" TO :"mlflow_user";
CREATE SCHEMA IF NOT EXISTS mlflow AUTHORIZATION :"mlflow_user";