import json
from uuid import UUID

from fastapi import Request
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS app.predictions (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_key    text             NOT NULL,
    model_version text,
    user_id      text,
    created_at   timestamptz      NOT NULL DEFAULT now(),
    inputs       jsonb            NOT NULL,
    prediction   double precision NOT NULL,
    n_missing    integer          NOT NULL,
    feedback     text CHECK (feedback IN ('like', 'dislike')),
    feedback_at  timestamptz
);
CREATE INDEX IF NOT EXISTS predictions_model_created_idx ON app.predictions (model_key, created_at DESC);

CREATE TABLE IF NOT EXISTS app.chat_conversations (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     text        NOT NULL,                 -- "<provider>:<stable id>"
    user_name   text,
    title       text        NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS chat_conversations_user_idx ON app.chat_conversations (user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS app.chat_messages (
    seq              bigint GENERATED ALWAYS AS IDENTITY,  -- message order: timestamps can tie
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id  uuid NOT NULL REFERENCES app.chat_conversations (id) ON DELETE CASCADE,
    role             text NOT NULL CHECK (role IN ('user', 'assistant')),
    content          text NOT NULL,
    payload          jsonb,                                -- assistant: {"table": ..., "trace": ...}
    created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS chat_messages_conversation_idx ON app.chat_messages (conversation_id, seq);
"""


def _jsonb(value: object) -> Jsonb:
    """
    Converts object to Jsonb
    """
    return Jsonb(value, dumps=lambda v: json.dumps(v, default=str))


class PredictionStore:
    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    def save_prediction(
        self,
        model_key: str,
        model_version: str,
        user_id: str | None,
        inputs: dict,
        prediction: float,
        n_missing: int,
    ) -> UUID:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO app.predictions (model_key, model_version, user_id, inputs, prediction, n_missing)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    model_key,
                    model_version,
                    user_id,
                    _jsonb(inputs),
                    prediction,
                    n_missing,
                ),
            ).fetchone()
        return row[0]

    def save_feedback(self, pred_id: UUID, value: str) -> bool:
        """False if the prediction doesn't exist."""
        with self._pool.connection() as conn:
            cur = conn.execute(
                "UPDATE app.predictions SET feedback = %s, feedback_at = now() WHERE id = %s",
                (value, pred_id),
            )
            return cur.rowcount == 1

    def recent(self, model_key: str, limit: int = 25) -> list[dict]:
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, created_at, model_version, prediction, n_missing, feedback
                FROM app.predictions
                WHERE model_key = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (model_key, limit),
            )
            return cur.fetchall()

    def monitoring(self, model_key: str) -> dict:
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*)                                     AS n_predictions,
                    AVG(prediction)                              AS mean_prediction,
                    AVG(n_missing)                               AS mean_missing,
                    COUNT(*) FILTER (WHERE feedback = 'like')    AS likes,
                    COUNT(*) FILTER (WHERE feedback = 'dislike') AS dislikes,
                    MAX(created_at)                              AS last_prediction_at
                FROM app.predictions
                WHERE model_key = %s
                """,
                (model_key,),
            )
            return cur.fetchone()


class ChatStore:
    """Every method that reads or changes a conversation takes the user's ID:
    a user can only ever see or delete their own conversations."""

    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    def create_conversation(
        self, user_id: str, user_name: str | None, title: str
    ) -> UUID:
        with self._pool.connection() as conn:
            row = conn.execute(
                "INSERT INTO app.chat_conversations (user_id, user_name, title) VALUES (%s, %s, %s) RETURNING id",
                (user_id, user_name, title),
            ).fetchone()
        return row[0]

    def get_conversation(self, conversation_id: UUID, user_id: str) -> dict | None:
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, title, created_at, updated_at
                FROM app.chat_conversations
                WHERE id = %s AND user_id = %s
                """,
                (conversation_id, user_id),
            )
            return cur.fetchone()

    def list_conversations(self, user_id: str, limit: int = 50) -> list[dict]:
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, title, created_at, updated_at
                FROM app.chat_conversations
                WHERE user_id = %s
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                (user_id, limit),
            )
            return cur.fetchall()

    def add_message(
        self,
        conversation_id: UUID,
        role: str,
        content: str,
        payload: dict | None = None,
    ) -> dict:
        """Add a message and touch the conversation, in one transaction."""
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO app.chat_messages (conversation_id, role, content, payload)
                VALUES (%s, %s, %s, %s)
                RETURNING id, role, content, payload, created_at
                """,
                (
                    conversation_id,
                    role,
                    content,
                    _jsonb(payload) if payload is not None else None,
                ),
            )
            row = cur.fetchone()
            cur.execute(
                "UPDATE app.chat_conversations SET updated_at = now() WHERE id = %s",
                (conversation_id,),
            )
            return row

    def get_messages(self, conversation_id: UUID) -> list[dict]:
        """Caller must have checked ownership with get_conversation first."""
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, role, content, payload, created_at
                FROM app.chat_messages
                WHERE conversation_id = %s
                ORDER BY seq
                """,
                (conversation_id,),
            )
            return cur.fetchall()

    def delete_conversation(self, conversation_id: UUID, user_id: str) -> bool:
        with self._pool.connection() as conn:
            cur = conn.execute(
                "DELETE FROM app.chat_conversations WHERE id = %s AND user_id = %s",
                (conversation_id, user_id),
            )
            return cur.rowcount == 1

    def delete_older_than(self, days: int) -> int:
        """Retention: delete conversations untouched for `days` days (their messages cascade)."""
        with self._pool.connection() as conn:
            cur = conn.execute(
                "DELETE FROM app.chat_conversations WHERE updated_at < now() - make_interval(days => %s)",
                (days,),
            )
            return cur.rowcount


def get_prediction_store(request: Request) -> PredictionStore:
    return request.app.state.predictions


def get_chat_store(request: Request) -> ChatStore:
    return request.app.state.chats
