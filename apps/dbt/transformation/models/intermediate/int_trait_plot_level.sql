-- int_trait_plot_level
-- One row = one plot × one trait (cleaned value).
--
-- Source:  stg_trials.
-- Traits:  only numeric traits in trait_dictionary with agent_enabled = TRUE.
-- Rows:    empty values are dropped.

WITH source AS (
    SELECT *
    FROM {{ ref('stg_trials') }}
),

dictionary AS (
    SELECT LOWER(TRIM(trait)) AS trait
    FROM {{ ref('trait_dictionary') }}
    WHERE LOWER(TRIM(data_type)) = 'float' AND agent_enabled = TRUE
),

final_trait_long AS (
    SELECT
        s._dlt_id,
        s.variety,
        s.experiment_name,
        s.location,
        s.env_type,
        s.plot,
        s.year,
        kv.key                              AS trait,
        CAST(kv.value AS DOUBLE PRECISION)  AS value
    FROM source AS s
    CROSS JOIN LATERAL jsonb_each(to_jsonb(s)) AS kv
    INNER JOIN dictionary AS d ON kv.key = d.trait
    WHERE jsonb_typeof(kv.value) = 'number'
)

SELECT * FROM final_trait_long