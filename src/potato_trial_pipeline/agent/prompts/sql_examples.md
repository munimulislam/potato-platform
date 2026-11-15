# Examples (copy these patterns)

Q: How many trials were at Oak Park?

```sql
SELECT COUNT(DISTINCT experiment_name) AS n_trials
FROM main.int_trait_experiment_level
WHERE location = 'oak park' AND value IS NOT NULL
```

Q: Which years have mealiness data?

```sql
SELECT DISTINCT year
FROM main.int_trait_experiment_level
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
       AVG(e.value) AS mean, MEDIAN(e.value) AS median, STDDEV_SAMP(e.value) AS sd,
       MIN(e.value) AS min, MAX(e.value) AS max,
       QUANTILE_CONT(e.value, 0.10) AS p10, QUANTILE_CONT(e.value, 0.25) AS p25,
       QUANTILE_CONT(e.value, 0.75) AS p75, QUANTILE_CONT(e.value, 0.90) AS p90
FROM main.trait_dictionary AS d
LEFT JOIN main.int_trait_experiment_level AS e ON e.trait = d.trait
WHERE d.trait = 'mealiness'
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
       AVG(value) AS mean, MEDIAN(value) AS median, STDDEV_SAMP(value) AS sd,
       MIN(value) AS min, MAX(value) AS max,
       QUANTILE_CONT(value, 0.10) AS p10, QUANTILE_CONT(value, 0.25) AS p25,
       QUANTILE_CONT(value, 0.75) AS p75, QUANTILE_CONT(value, 0.90) AS p90
FROM main.int_trait_experiment_level
WHERE location = 'oak park'
GROUP BY trait
ORDER BY n_trials DESC
```

````

Q: Which locations are in the Mediterranean region?

```sql
SELECT location, COUNT(DISTINCT experiment_name) AS n_trials
FROM main.int_trait_experiment_level
WHERE env_type = 'med' AND value IS NOT NULL
GROUP BY location
ORDER BY n_trials DESC
````

Q: How many varieties were trialled in 2019?

```sql
SELECT COUNT(DISTINCT variety) AS n_varieties
FROM main.int_trait_experiment_level
WHERE year = 2019 AND value IS NOT NULL
```

Q: Which traits were measured at Seville?

```sql
SELECT trait, COUNT(DISTINCT experiment_name) AS n_trials
FROM main.int_trait_experiment_level
WHERE location = 'seville' AND value IS NOT NULL
GROUP BY trait
ORDER BY n_trials DESC
```

Q: Tell me about Supernova.

```sql
SELECT variety,
       COUNT(DISTINCT experiment_name) AS n_trials,
       MIN(year) AS first_year, MAX(year) AS last_year,
       LIST(DISTINCT location ORDER BY location) AS locations
FROM main.int_trait_experiment_level
WHERE variety ILIKE '%supernova%' AND value IS NOT NULL
GROUP BY variety
```

Q: How many trials per year were there in North Europe?

```sql
SELECT year, COUNT(DISTINCT experiment_name) AS n_trials
FROM main.int_trait_experiment_level
WHERE env_type = 'ne' AND value IS NOT NULL
GROUP BY year
ORDER BY year
```

Q: What mealiness scores did Cristina get in each trial?

```sql
SELECT experiment_name, year, location, value
FROM main.int_trait_experiment_level
WHERE variety ILIKE '%cristina%' AND trait = 'mealiness' AND value IS NOT NULL
ORDER BY year
```

Q: Which variety has the best mealiness?
Not SQL. Call rank_varieties with {"trait": "mealiness"}.
