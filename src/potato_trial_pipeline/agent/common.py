from enum import Enum


class ToolError(Exception):
    """An error the agent can show to the user or use to correct its call."""


class EnvType(str, Enum):
    NE = "ne"
    MED = "med"


ENV_LABELS = {
    EnvType.NE: "North Europe",
    EnvType.MED: "Mediterranean",
}


class TraitDirection(str, Enum):
    High = "High"
    Neutral = "Neutral"
    Low = "Low"
