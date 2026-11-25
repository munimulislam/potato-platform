from pathlib import Path
from typing import Any, Mapping

import dagster as dg
from dagster_dbt import DagsterDbtTranslator, DbtCliResource, dbt_assets

from potato_pipeline.defs.resources import dbt_project

if not Path(dbt_project.manifest_path).exists():
    raise FileNotFoundError(f"dbt manifest not found at {dbt_project.manifest_path}.")


class PotatoDbtTranslator(DagsterDbtTranslator):
    def get_automation_condition(
        self, dbt_resource_props: Mapping[str, Any]
    ) -> dg.AutomationCondition:
        return dg.AutomationCondition.eager()

    def get_group_name(self, dbt_resource_props: Mapping[str, Any]) -> str:
        explicit = super().get_group_name(dbt_resource_props)

        if explicit:
            return explicit

        fqn = dbt_resource_props.get("fqn", [])
        folder = fqn[1] if len(fqn) > 2 else "reference"
        return f"dbt_{folder}"


@dbt_assets(
    manifest=dbt_project.manifest_path,
    project=dbt_project,
    dagster_dbt_translator=PotatoDbtTranslator(),
)
def dbt_models(context: dg.AssetExecutionContext, dbt: DbtCliResource):
    yield from dbt.cli(["build"], context=context).stream()
