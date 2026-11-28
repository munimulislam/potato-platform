-- int_trait_plot_level
-- Source:  stg_trials.
-- meta columns like source or load information are excluded

WITH source AS (
    SELECT * FROM {{ref('stg_trials')}}
)

SELECT
    {{ dbt_utils.star(
        from=ref('stg_trials'),
        except=["source_file", "source_row", "_dlt_load_id", "_dlt_id"]
    ) }}
from source

