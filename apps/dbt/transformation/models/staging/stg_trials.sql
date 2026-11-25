-- stg_trials
-- One row = one plot. The cleaned wide table: one column per trait, same names as the source.
--
-- transformation:
--      only for numeric traits in trait_dictionary with data_type = 'float':
--         value -> NULL when outside valid_min / valid_max,
--         value -> NULL when the trait is 0 for every plot in the experiment (= not recorded).
--      Other traits:   columns not in the dictionary are kept as they are, no checks.
--      yield:    COALESCE(finalyield, yield_total_t_ha), merged AFTER cleaning.

-- depends_on: {{ ref('trait_dictionary') }}

{%- set id_columns = ['name1', 'experiment_name', 'location', 'plot', 'year'] -%}
{%- set columns = [] -%}
{%- set rules = {} -%}

{%- if execute -%}
    {%- set columns = adapter.get_columns_in_relation(source('raw_trial_data', 'valids')) -%}
    {%- set dictionary = run_query(
        "SELECT LOWER(TRIM(trait)) AS trait, valid_min, valid_max FROM " ~ ref('trait_dictionary') ~
        " WHERE LOWER(TRIM(data_type)) = 'float'"
    ) -%}
    {%- for row in dictionary.rows -%}
        {%- do rules.update({row['trait']: row}) -%}
    {%- endfor -%}
{%- endif %}

WITH source AS (
    SELECT *
    FROM {{ source('raw_trial_data', 'valids') }}
),

loc_map AS (
    SELECT
        LOWER(TRIM(raw_location)) AS location_key,
        LOWER(TRIM(location))     AS location,
        LOWER(TRIM(env_type))     AS env_type
    FROM {{ ref('location_map') }}
),

cleaned AS (
    SELECT
        LOWER(TRIM(s.name1))            AS variety,
        LOWER(TRIM(s.experiment_name))  AS experiment_name,
        m.location,
        m.env_type,
        CAST(s.plot AS BIGINT)          AS plot,
        CAST(s.year AS INTEGER)         AS year
    {%- for col in columns if col.name not in id_columns %},
        s.{{ adapter.quote(col.name) }}
    {%- endfor %}
    FROM source AS s
    LEFT JOIN loc_map AS m ON LOWER(TRIM(s.location)) = m.location_key
),

trait_cleaned AS (
    SELECT
        variety,
        experiment_name,
        location,
        env_type,
        plot,
        year
    {%- for col in columns if col.name not in id_columns %},
        {%- set c = adapter.quote(col.name) %}
        {%- set r = rules.get(col.name | lower) %}
        {%- if r is none %}
        {{ c }}
        {%- else %}
            {%- if not col.is_number() %}
                {{ exceptions.raise_compiler_error(
                    "stg_trials: '" ~ col.name ~ "' is a float trait in trait_dictionary, "
                    ~ "but raw.trials stores it as " ~ col.data_type ~ ". Fix the source file or the dictionary."
                ) }}
            {%- endif %}
        CASE
            WHEN MAX(ABS({{ c }})) OVER (PARTITION BY experiment_name) = 0 THEN NULL
            {%- if r['valid_min'] is not none %}
            WHEN {{ c }} < {{ r['valid_min'] }} THEN NULL
            {%- endif %}
            {%- if r['valid_max'] is not none %}
            WHEN {{ c }} > {{ r['valid_max'] }} THEN NULL
            {%- endif %}
            ELSE {{ c }}
        END AS {{ c }}
        {%- endif %}
    {%- endfor %}
    FROM cleaned
),

yield_merged AS (
    SELECT
        *,
        COALESCE(finalyield, yield_total_t_ha) AS yield
    FROM trait_cleaned
)

SELECT * FROM yield_merged