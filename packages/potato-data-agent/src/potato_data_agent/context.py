from dataclasses import dataclass

from psycopg_pool import ConnectionPool

from potato_data_agent.config import AgentConfig
from potato_data_agent.sql import SqlRunner


@dataclass(frozen=True)
class ToolContext:
    sql: SqlRunner
    config: AgentConfig

    @classmethod
    def create(cls, pool: ConnectionPool, config: AgentConfig) -> "ToolContext":
        return cls(
            sql=SqlRunner(pool, allowed_schemas=config.allowed_schemas),
            config=config,
        )
