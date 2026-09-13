"""Phase 17 PostgreSQL provider.

This adapter implements the same small database contract used by the existing
Supabase/PostgREST adapter, but talks directly to PostgreSQL. It intentionally
keeps PostgREST-style query dictionaries at the repository boundary so the
business/storage services do not need provider-specific branches.
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import date, datetime, time as dt_time
from decimal import Decimal
from uuid import UUID
from contextlib import contextmanager
from typing import Any, Mapping, Sequence

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SAFE_TABLES = {
    "ghostea_chat_registry",
    "ghostea_topic_registry",
    "ghostea_topic_settings",
    "ghostea_group_settings",
    "ghostea_warnings",
    "ghostea_warning_history",
    "ghostea_custom_filters",
    "ghostea_moderation_logs",
    "ghostea_join_events",
    "ghostea_raid_events",
    "ghostea_verifications",
    "ghostea_reputation",
    "ghostea_cleanup_runs",
    "ghostea_health_events",
    "ghostea_chat_migrations",
    "ghostea_user_admin_actions",
    "ghostea_security_locks",
    "ghostea_admins",
    "ghostea_user_directory",
    "ghostea_upload_sessions",
    "ghostea_resources",
    "ghostea_schema_meta",
    "ghostea_schema_migrations",
}


def _identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"Unsafe SQL identifier: {value!r}")
    return '"' + value.replace('"', '""') + '"'


def _table_name(table: str) -> str:
    if table not in _SAFE_TABLES:
        raise ValueError(f"Unsupported Ghostea table: {table}")
    return _identifier(table)


def _unwrap(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        try:
            from psycopg.types.json import Jsonb
            return Jsonb(value)
        except ImportError:
            return json.dumps(value)
    return value


def _json_safe(value: Any) -> Any:
    """Normalize PostgreSQL-native values to the JSON-like shapes returned by PostgREST."""
    if isinstance(value, (datetime, date, dt_time)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        # PostgreSQL numeric values are JSON numbers in PostgREST. Preserve
        # integers exactly and use float for non-integral values.
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _rows(cur) -> list[dict[str, Any]]:
    columns = [d.name for d in cur.description]
    return [{column: _json_safe(value) for column, value in zip(columns, row)} for row in cur.fetchall()]


def _parse_in(value: str) -> list[str]:
    if not (value.startswith("(") and value.endswith(")")):
        raise ValueError(f"Invalid IN expression: {value}")
    inner = value[1:-1]
    if not inner:
        return []
    return [item.strip() for item in inner.split(",")]


def _coerce(value: str) -> Any:
    if value == "null":
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    # Keep timestamps and arbitrary text as strings; PostgreSQL infers the
    # target type from the column operator.
    try:
        if re.fullmatch(r"-?\d+", value):
            return int(value)
        if re.fullmatch(r"-?\d+\.\d+", value):
            return float(value)
    except Exception:
        pass
    return value


def _condition(column: str, expression: str, params: list[Any]) -> str:
    col = _identifier(column)
    expression = str(expression)
    negated_in = expression.startswith("not.in.")
    if negated_in:
        items = _parse_in(expression[7:])
        if not items:
            return "TRUE"
        params.extend(_coerce(x) for x in items)
        return f"{col} NOT IN ({', '.join(['%s'] * len(items))})"

    for op_name, sql_op in (
        ("gte", ">="), ("lte", "<="), ("neq", "<>"),
        ("gt", ">"), ("lt", "<"), ("eq", "="),
        ("ilike", "ILIKE"), ("like", "LIKE"),
    ):
        prefix = op_name + "."
        if expression.startswith(prefix):
            raw = expression[len(prefix):]
            params.append(_coerce(raw))
            if raw == "null" and op_name == "eq":
                return f"{col} IS NULL"
            if raw == "null" and op_name == "neq":
                return f"{col} IS NOT NULL"
            return f"{col} {sql_op} %s"

    if expression.startswith("in."):
        items = _parse_in(expression[3:])
        if not items:
            return "FALSE"
        params.extend(_coerce(x) for x in items)
        return f"{col} IN ({', '.join(['%s'] * len(items))})"

    if expression.startswith("is."):
        raw = expression[3:]
        if raw == "null":
            return f"{col} IS NULL"
        if raw == "true":
            return f"{col} IS TRUE"
        if raw == "false":
            return f"{col} IS FALSE"

    raise ValueError(f"Unsupported PostgreSQL filter expression for {column}: {expression}")


def build_select_query(table: str, query: Mapping[str, Any]):
    """Translate the subset of PostgREST filters Ghostea uses into SQL."""
    query = dict(query or {})
    params: list[Any] = []
    selected = str(query.get("select", "*"))
    if selected != "*":
        columns = [x.strip() for x in selected.split(",") if x.strip()]
        if not columns or any(not _IDENTIFIER.fullmatch(x) for x in columns):
            raise ValueError("Unsafe select column")
        select_sql = ", ".join(_identifier(x) for x in columns)
    else:
        select_sql = "*"

    sql = f"SELECT {select_sql} FROM {_table_name(table)}"
    where = []
    reserved = {"select", "order", "limit", "offset"}
    for key, value in query.items():
        if key in reserved:
            continue
        where.append(_condition(key, str(value), params))
    if where:
        sql += " WHERE " + " AND ".join(where)

    order = query.get("order")
    if order:
        order_parts = []
        for part in str(order).split(","):
            bits = part.strip().split(".")
            if len(bits) not in (2, 3) or not _IDENTIFIER.fullmatch(bits[0]):
                raise ValueError("Unsafe order expression")
            direction = bits[1].lower()
            if direction not in {"asc", "desc"}:
                raise ValueError("Unsupported order direction")
            nulls = ""
            if len(bits) == 3:
                if bits[2].lower() not in {"nullsfirst", "nullslast"}:
                    raise ValueError("Unsupported order null placement")
                nulls = " NULLS " + ("FIRST" if bits[2].lower() == "nullsfirst" else "LAST")
            order_parts.append(f"{_identifier(bits[0])} {direction.upper()}{nulls}")
        sql += " ORDER BY " + ", ".join(order_parts)

    if "limit" in query:
        limit = max(0, min(int(query["limit"]), 5000))
        sql += " LIMIT %s"
        params.append(limit)
    if "offset" in query:
        offset = max(0, int(query["offset"]))
        sql += " OFFSET %s"
        params.append(offset)
    return sql, params


class PostgreSQL:
    """Direct PostgreSQL implementation of Ghostea's DatabaseProvider."""

    def __init__(self, dsn: str | None = None):
        self.dsn = (dsn or os.getenv("DATABASE_URL", "")).strip()
        if not self.dsn:
            raise RuntimeError("PostgreSQL provider requires DATABASE_URL.")
        if not self.dsn.startswith(("postgresql://", "postgres://")):
            raise RuntimeError("DATABASE_URL must be a PostgreSQL connection URL.")
        self._local = threading.local()
        self._lock = threading.RLock()

    @staticmethod
    def _connect_timeout():
        try:
            value = int(os.getenv("DATABASE_CONNECT_TIMEOUT_SECONDS", "10").strip())
        except (TypeError, ValueError):
            value = 10
        return max(3, min(value, 120))

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL provider requires psycopg. Install project requirements first."
            ) from exc
        conn = getattr(self._local, "connection", None)
        if conn is None or conn.closed:
            conn = psycopg.connect(
                self.dsn,
                autocommit=True,
                connect_timeout=self._connect_timeout(),
            )
            self._local.connection = conn
        return conn

    @contextmanager
    def _cursor(self):
        with self._lock:
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    yield cur
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise

    def select(self, table: str, query: Mapping[str, Any]):
        sql, params = build_select_query(table, query)
        with self._cursor() as cur:
            cur.execute(sql, params)
            return _rows(cur)

    def insert(self, table: str, payload: Any, return_rows: bool = False):
        if not isinstance(payload, Mapping) or not payload:
            raise ValueError("insert payload must be a non-empty mapping")
        columns = list(payload)
        if any(not _IDENTIFIER.fullmatch(c) for c in columns):
            raise ValueError("Unsafe insert column")
        values = [_unwrap(payload[c]) for c in columns]
        sql = (
            f"INSERT INTO {_table_name(table)} "
            f"({', '.join(_identifier(c) for c in columns)}) "
            f"VALUES ({', '.join(['%s'] * len(columns))})"
        )
        if return_rows:
            sql += " RETURNING *"
        with self._cursor() as cur:
            cur.execute(sql, values)
            if not return_rows:
                return []
            return _rows(cur)

    def _unique_columns(self, table: str, cur) -> list[str]:
        cur.execute(
            """
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a
              ON a.attrelid = i.indrelid
             AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = %s::regclass
              AND (i.indisprimary OR i.indisunique)
            ORDER BY i.indisprimary DESC, i.indexrelid, a.attnum
            """,
            (table,),
        )
        rows = cur.fetchall()
        # Prefer the first complete PK/unique index. Ghostea's upserts all
        # target a known PK/unique identity and this avoids hard-coded schema.
        if not rows:
            raise RuntimeError(f"No primary/unique key found for {table}")
        first_index = None
        cur.execute(
            """
            SELECT i.indexrelid::text, i.indisprimary, i.indisunique,
                   array_agg(a.attname ORDER BY k.ord) AS cols
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=ANY(i.indkey)
            CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS k(attnum, ord)
            WHERE i.indrelid=%s::regclass AND (i.indisprimary OR i.indisunique)
              AND a.attnum=k.attnum
            GROUP BY i.indexrelid, i.indisprimary, i.indisunique
            ORDER BY i.indisprimary DESC, i.indexrelid
            LIMIT 1
            """,
            (table,),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError(f"No primary/unique key found for {table}")
        return list(row[3])

    def upsert(self, table: str, payload: Any):
        if not isinstance(payload, Mapping) or not payload:
            raise ValueError("upsert payload must be a non-empty mapping")
        columns = list(payload)
        if any(not _IDENTIFIER.fullmatch(c) for c in columns):
            raise ValueError("Unsafe upsert column")
        values = [_unwrap(payload[c]) for c in columns]
        with self._cursor() as cur:
            conflict = self._unique_columns(table, cur)
            if any(c not in columns for c in conflict):
                raise ValueError(
                    f"Upsert payload for {table} does not include its unique key: {conflict}"
                )
            updates = [c for c in columns if c not in conflict]
            sql = (
                f"INSERT INTO {_table_name(table)} "
                f"({', '.join(_identifier(c) for c in columns)}) "
                f"VALUES ({', '.join(['%s'] * len(columns))}) "
                f"ON CONFLICT ({', '.join(_identifier(c) for c in conflict)}) "
            )
            if updates:
                sql += "DO UPDATE SET " + ", ".join(
                    f"{_identifier(c)}=EXCLUDED.{_identifier(c)}" for c in updates
                )
            else:
                sql += "DO NOTHING"
            sql += " RETURNING *"
            cur.execute(sql, values)
            return _rows(cur)

    def update(self, table: str, payload: Any, query: Mapping[str, Any]):
        if not isinstance(payload, Mapping) or not payload:
            raise ValueError("update payload must be a non-empty mapping")
        columns = list(payload)
        if any(not _IDENTIFIER.fullmatch(c) for c in columns):
            raise ValueError("Unsafe update column")
        values = [_unwrap(payload[c]) for c in columns]
        where_sql, where_params = build_select_query(table, {**dict(query), "select": "id"} if query else {"select": "id"})
        # Reuse the WHERE parser but strip the SELECT prefix.
        where_clause = where_sql.split(" WHERE ", 1)[1] if " WHERE " in where_sql else "TRUE"
        # build_select_query can append ORDER/LIMIT; update queries in Ghostea
        # intentionally use only equality filters, so reject those modifiers.
        if any(k in query for k in ("order", "limit", "offset")):
            raise ValueError("ORDER/LIMIT/OFFSET are not supported for updates")
        sql = (
            f"UPDATE {_table_name(table)} SET "
            + ", ".join(f"{_identifier(c)}=%s" for c in columns)
            + " WHERE " + where_clause
            + " RETURNING *"
        )
        with self._cursor() as cur:
            cur.execute(sql, values + where_params)
            return _rows(cur)

    def delete(self, table: str, query: Mapping[str, Any]):
        where_sql, where_params = build_select_query(table, {**dict(query), "select": "id"} if query else {"select": "id"})
        where_clause = where_sql.split(" WHERE ", 1)[1] if " WHERE " in where_sql else "TRUE"
        if any(k in query for k in ("order", "limit", "offset")):
            raise ValueError("ORDER/LIMIT/OFFSET are not supported for deletes")
        sql = f"DELETE FROM {_table_name(table)} WHERE {where_clause} RETURNING *"
        with self._cursor() as cur:
            cur.execute(sql, where_params)
            return _rows(cur)

    def check_tables(self, tables: Sequence[str]):
        result = {}
        with self._cursor() as cur:
            for table in tables:
                if table not in _SAFE_TABLES:
                    result[table] = False
                    continue
                cur.execute(
                    "SELECT to_regclass(%s)",
                    (table,),
                )
                result[table] = cur.fetchone()[0] is not None
        return result

    def count(self, table: str, query: Mapping[str, Any] | None = None):
        query = dict(query or {})
        params: list[Any] = []
        where = []
        for key, value in query.items():
            if key in {"select", "order", "limit", "offset"}:
                continue
            where.append(_condition(key, str(value), params))
        sql = f"SELECT COUNT(*) FROM {_table_name(table)}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        with self._cursor() as cur:
            cur.execute(sql, params)
            return int(cur.fetchone()[0])

    def health_check(self) -> bool:
        """Perform a lightweight database connectivity check."""
        with self._cursor() as cur:
            cur.execute("SELECT 1")
            return cur.fetchone()[0] == 1

    def close(self):
        conn = getattr(self._local, "connection", None)
        if conn is not None and not conn.closed:
            conn.close()
            self._local.connection = None
