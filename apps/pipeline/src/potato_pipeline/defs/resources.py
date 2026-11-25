import os
from pathlib import Path

import dagster as dg
from dagster_dbt import DbtCliResource, DbtProject
from dagster_dlt import DagsterDltResource

dbt_project_directory = str(dg.EnvVar("DBT_PROFILES_DIR").get_value())
dbt_project = DbtProject(project_dir=dbt_project_directory)


DBT_PROJECT_DIR = Path(os.environ["DBT_PROJECT_DIR"]).resolve()

dbt_project = DbtProject(project_dir=DBT_PROJECT_DIR, profiles_dir=DBT_PROJECT_DIR)

dbt_resource = DbtCliResource(project_dir=dbt_project)
dlt_resource = DagsterDltResource()


@dg.definitions
def resources() -> dg.Definitions:
    return dg.Definitions(resources={"dbt": dbt_resource, "dlt": dlt_resource})
