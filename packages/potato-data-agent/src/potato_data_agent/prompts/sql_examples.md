# Example run_sql calls

Each example is a question and the SQL to pass as the `sql` argument of the run_sql tool.
Never write SQL in your reply unless user explicitly asks for it. Call run_sql, wait for its result, then answer in plain words.

Q: How many trials were at Oak Park?

```sql
SELECT COUNT(DISTINCT experiment_name) AS n_trials
FROM intermediate.int_trait_experiment_level
WHERE location = 'oak park' AND value IS NOT NULL
```

Q: Which years have mealiness data?

```sql
SELECT DISTINCT year
FROM intermediate.int_trait_experiment_level
WHERE trait = 'mealiness' AND value IS NOT NULL
ORDER BY year
```

Q: Tell me about the mealiness trait.

```sql
SELECT d.label, d.description, d.scale, d.direction,
       COUNT(DISTINCT e.experiment_name) FILTER (WHERE e.value IS NOT NULL) AS n_trials,
       COUNT(DISTINCT e.variety) FILTER (WHERE e.value IS NOT NULL) AS n_varieties,
       COUNT(DISTINCT e.location) FILTER (WHERE e.value IS NOT NULL) AS n_locations,
       COUNT(DISTINCT e.year) FILTER (WHERE e.value IS NOT NULL) AS n_years,
       MIN(e.year) FILTER (WHERE e.value IS NOT NULL) AS first_year,
       MAX(e.year) FILTER (WHERE e.value IS NOT NULL) AS last_year,
       COUNT(e.value) AS n_values,
       ROUND(100.0 * COUNT(e.trait) FILTER (WHERE e.value IS NULL)
             / NULLIF(COUNT(e.trait), 0), 1) AS pct_missing,
       ROUND(AVG(e.value)::numeric, 2) AS mean,
       ROUND((percentile_cont(0.5) WITHIN GROUP (ORDER BY e.value))::numeric, 2) AS median,
       ROUND(STDDEV_SAMP(e.value)::numeric, 2) AS sd,
       MIN(e.value) AS min, MAX(e.value) AS max,
       ROUND((percentile_cont(0.10) WITHIN GROUP (ORDER BY e.value))::numeric, 2) AS p10,
       ROUND((percentile_cont(0.25) WITHIN GROUP (ORDER BY e.value))::numeric, 2) AS p25,
       ROUND((percentile_cont(0.75) WITHIN GROUP (ORDER BY e.value))::numeric, 2) AS p75,
       ROUND((percentile_cont(0.90) WITHIN GROUP (ORDER BY e.value))::numeric, 2) AS p90
FROM reference.trait_dictionary AS d
LEFT JOIN intermediate.int_trait_experiment_level AS e ON e.trait = LOWER(TRIM(d.trait))
WHERE LOWER(TRIM(d.trait)) = 'mealiness'
GROUP BY d.label, d.description, d.scale, d.direction
```

Q: Tell me about Oak Park.
(For a region use WHERE env_type = 'ne'; for a year use WHERE year = 2019. Statistics are
per trait, because different traits have different scales.)

```sql
SELECT trait,
       COUNT(DISTINCT experiment_name) FILTER (WHERE value IS NOT NULL) AS n_trials,
       COUNT(DISTINCT variety) FILTER (WHERE value IS NOT NULL) AS n_varieties,
       COUNT(DISTINCT location) FILTER (WHERE value IS NOT NULL) AS n_locations,
       COUNT(DISTINCT year) FILTER (WHERE value IS NOT NULL) AS n_years,
       MIN(year) FILTER (WHERE value IS NOT NULL) AS first_year,
       MAX(year) FILTER (WHERE value IS NOT NULL) AS last_year,
       COUNT(value) AS n_values,
       ROUND(100.0 * COUNT(*) FILTER (WHERE value IS NULL) / COUNT(*), 1) AS pct_missing,
       ROUND(AVG(value)::numeric, 2) AS mean,
       ROUND((percentile_cont(0.5) WITHIN GROUP (ORDER BY value))::numeric, 2) AS median,
       ROUND(STDDEV_SAMP(value)::numeric, 2) AS sd,
       MIN(value) AS min, MAX(value) AS max,
       ROUND((percentile_cont(0.10) WITHIN GROUP (ORDER BY value))::numeric, 2) AS p10,
       ROUND((percentile_cont(0.25) WITHIN GROUP (ORDER BY value))::numeric, 2) AS p25,
       ROUND((percentile_cont(0.75) WITHIN GROUP (ORDER BY value))::numeric, 2) AS p75,
       ROUND((percentile_cont(0.90) WITHIN GROUP (ORDER BY value))::numeric, 2) AS p90
FROM intermediate.int_trait_experiment_level
WHERE location = 'oak park'
GROUP BY trait
ORDER BY n_trials DESC
```

Q: Which locations are in the Mediterranean region?

```sql
SELECT location, COUNT(DISTINCT experiment_name) AS n_trials
FROM intermediate.int_trait_experiment_level
WHERE env_type = 'med' AND value IS NOT NULL
GROUP BY location
ORDER BY n_trials DESC
```

Q: How many varieties were trialled in 2019?

```sql
SELECT COUNT(DISTINCT variety) AS n_varieties
FROM intermediate.int_trait_experiment_level
WHERE year = 2019 AND value IS NOT NULL
```

Q: Which traits were measured at Seville?

```sql
SELECT trait, COUNT(DISTINCT experiment_name) AS n_trials
FROM intermediate.int_trait_experiment_level
WHERE location = 'seville' AND value IS NOT NULL
GROUP BY trait
ORDER BY n_trials DESC
```

Q: Tell me about Supernova.

```sql
SELECT variety,
       COUNT(DISTINCT experiment_name) AS n_trials,
       MIN(year) AS first_year, MAX(year) AS last_year,
       string_agg(DISTINCT location, ', ' ORDER BY location) AS locations
FROM intermediate.int_trait_experiment_level
WHERE variety ILIKE '%supernova%' AND value IS NOT NULL
GROUP BY variety
```

Q: How many trials per year were there in North Europe?

```sql
SELECT year, COUNT(DISTINCT experiment_name) AS n_trials
FROM intermediate.int_trait_experiment_level
WHERE env_type = 'ne' AND value IS NOT NULL
GROUP BY year
ORDER BY year
```

Q: What mealiness scores did Cristina get in each trial?

```sql
SELECT experiment_name, year, location, value
FROM intermediate.int_trait_experiment_level
WHERE variety ILIKE '%cristina%' AND trait = 'mealiness' AND value IS NOT NULL
ORDER BY year
```

Q: Which variety has the best mealiness?
Not SQL. Call rank_varieties with {"trait": "mealiness"}.