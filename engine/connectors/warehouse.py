"""Tier 2: a generic SQL warehouse, mapped per evidence kind in config/warehouse.yaml."""

from __future__ import annotations

import re
from typing import Any

import psycopg
from psycopg.rows import dict_row

from engine.connectors.base import BaseConnector, EvidenceBundle, Window, make_bundle
from engine.connectors.common import fmt_window, frame
from engine.settings import env, load_config

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


class Warehouse(BaseConnector):
    name = "warehouse"
    tier = 2
    priority = 1

    def __init__(self) -> None:
        self.cfg = load_config("warehouse")
        self.kinds = tuple(self.cfg.get("kinds", {}))  # type: ignore[misc]
        self.unavailable_reason = f"needs {self.cfg.get('dsn_env', 'WAREHOUSE_URL')}"

    async def available(self) -> bool:
        return bool(env(self.cfg.get("dsn_env", "WAREHOUSE_URL")))

    async def fetch(
        self, kind: str, window: Window | None, filters: dict[str, Any] | None = None
    ) -> EvidenceBundle:
        k = self.cfg["kinds"][kind]
        table, tcol = k["table"], k["time_column"]
        if not (_IDENT.match(table) and _IDENT.match(tcol)):
            raise ValueError("bad table or column name in warehouse config")
        cols = ", ".join(
            f"{expr} AS {name}" for name, expr in k["columns"].items()
        )  # config is operator-controlled
        sql = f"SELECT {cols} FROM {table}"
        params: list[Any] = []
        if window:
            sql += f" WHERE {tcol} >= %s AND {tcol} < %s"
            params = [window.start, window.end]
        sql += f" ORDER BY {tcol} LIMIT 200000"
        async with await psycopg.AsyncConnection.connect(
            env(self.cfg["dsn_env"]), row_factory=dict_row
        ) as conn:
            await conn.execute("SET TIME ZONE 'UTC'")
            rows = await (await conn.execute(sql, params)).fetchall()
        df = frame(rows, kind)
        return make_bundle(
            kind,
            self,
            df,
            window,
            query={"table": table},
            summary=f"{df.height:,} {kind.replace('_', ' ')} rows from the warehouse table {table}, "
            f"{fmt_window(window)}",
            data_ref={"source": f"warehouse:{table}"},
        )
