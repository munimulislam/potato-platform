import duckdb
import pytest

DICTIONARY_COLUMNS = """
    trait VARCHAR, data_type VARCHAR, label VARCHAR, direction VARCHAR,
    trait_group VARCHAR, scale VARCHAR, valid_min DOUBLE, valid_max DOUBLE,
    synonyms_keywords VARCHAR, description VARCHAR, agent_enabled BOOLEAN
"""

EXPERIMENT_COLUMNS = """
    variety VARCHAR, experiment_name VARCHAR, trait VARCHAR, year INTEGER,
    env_type VARCHAR, location VARCHAR, value DOUBLE
"""


@pytest.fixture
def make_db(tmp_path):
    """Build a small DuckDB file with the tables the agent tools read.

    dictionary: (trait, data_type, direction, agent_enabled) per row; the other
                dictionary columns get simple defaults (valid_min stays NULL).
    experiments: (variety, experiment_name, trait, year, env_type, location, value)
    """

    def _make(dictionary, experiments=(), location_map=()):
        path = tmp_path / "test.duckdb"
        conn = duckdb.connect(str(path))
        conn.execute(f"CREATE TABLE main.trait_dictionary ({DICTIONARY_COLUMNS})")
        conn.executemany(
            "INSERT INTO main.trait_dictionary VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    trait,
                    data_type,
                    trait.upper(),
                    direction,
                    "group",
                    "1-9",
                    None,
                    9.0,
                    None,
                    f"{trait} description",
                    enabled,
                )
                for trait, data_type, direction, enabled in dictionary
            ],
        )
        conn.execute(
            f"CREATE TABLE main.int_trait_experiment_level ({EXPERIMENT_COLUMNS})"
        )
        if experiments:
            conn.executemany(
                "INSERT INTO main.int_trait_experiment_level VALUES (?, ?, ?, ?, ?, ?, ?)",
                experiments,
            )
        conn.execute(
            "CREATE TABLE main.location_map (location VARCHAR, env_type VARCHAR)"
        )
        if location_map:
            conn.executemany(
                "INSERT INTO main.location_map VALUES (?, ?)", location_map
            )
        conn.close()
        return path

    return _make
