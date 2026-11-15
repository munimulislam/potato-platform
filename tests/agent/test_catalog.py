"""
Tests for catalog.py: the single place that decides which traits exist and which can be ranked.
describe_data and rank_varieties both rely on it, so a bug here breaks both tools.
"""

import duckdb
import pytest
from pydantic import ValidationError

from potato_trial_pipeline.agent.catalog import Trait, get_traits, is_rankable
from potato_trial_pipeline.agent.common import TraitDirection


def trait(data_type="float", direction="High") -> Trait:
    return Trait(trait="x", data_type=data_type, label="X", direction=direction)


@pytest.mark.parametrize(
    "data_type, direction, expected",
    [
        ("float", "High", True),
        ("float", "Low", True),
        ("float", "Neutral", False),  # no "better" direction -> cannot rank
        ("str", "High", False),  # text traits cannot be ranked by a mixed model
    ],
)
def test_is_rankable(data_type, direction, expected):
    assert is_rankable(trait(data_type, direction)) is expected


@pytest.mark.parametrize("bad", ["high", "higher_better", "up", ""])
def test_direction_outside_high_low_neutral_is_rejected(bad):
    # Directions are exactly High / Low / Neutral. Anything else must fail loudly
    # (and should already be stopped by the dbt accepted_values test).
    with pytest.raises(ValidationError):
        trait(direction=bad)


def test_get_traits_returns_enabled_traits_normalised(make_db):
    path = make_db(
        [
            ("o_a_score", "float", "High", True),
            (" FFDefects ", "FLOAT", "Low", True),  # messy spacing and case in the seed
            ("ffrots", "float", "High", False),  # disabled
        ]
    )
    with duckdb.connect(str(path), read_only=True) as conn:
        traits = get_traits(conn)

    assert [t.trait for t in traits] == ["ffdefects", "o_a_score"]
    assert traits[0].data_type == "float"
    assert traits[0].direction is TraitDirection.Low
