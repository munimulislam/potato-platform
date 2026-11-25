import dagster as dg

from potato_pipeline.defs.resources import dbt_resource
from potato_pipeline.defs.transform.assets import dbt_models


@dg.definitions
def definitions():
    return dg.Definitions(
        assets=[dbt_models],
        resources={"dbt": dbt_resource},
    )
