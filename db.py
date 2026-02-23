"""Thin Supabase/PostgREST client.

Implements a tiny subset of supabase-py style used by this project:
- table(name).insert(row).execute()
- table(name).select(...).eq(...).gte(...).lt(...).execute()
- table(name).upsert(row, on_conflict=...).execute()
"""
from __future__ import annotations

import httpx


class SelectBuilder:
    def __init__(self, client: httpx.Client, table: str, columns: str = "*"):
        self._client = client
        self._table = table
        self._params: list[tuple[str, str]] = [("select", columns or "*")]

    def eq(self, col: str, val):
        self._params.append((col, f"eq.{val}"))
        return self

    def gte(self, col: str, val):
        self._params.append((col, f"gte.{val}"))
        return self

    def lt(self, col: str, val):
        self._params.append((col, f"lt.{val}"))
        return self

    def execute(self):
        response = self._client.get(f"/{self._table}", params=self._params)
        response.raise_for_status()
        payload = response.json()
        return type("Resp", (), {"data": payload if payload is not None else []})()


class InsertBuilder:
    def __init__(self, client: httpx.Client, table: str, row: dict):
        self._client = client
        self._table = table
        self._row = row

    def execute(self):
        response = self._client.post(f"/{self._table}", json=self._row)
        response.raise_for_status()
        return type("Resp", (), {"data": None})()


class UpsertBuilder:
    def __init__(self, client: httpx.Client, table: str, row: dict, on_conflict: str):
        self._client = client
        self._table = table
        self._row = row
        self._on_conflict = on_conflict

    def execute(self):
        response = self._client.post(
            f"/{self._table}",
            params={"on_conflict": self._on_conflict},
            json=self._row,
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
        )
        response.raise_for_status()
        return type("Resp", (), {"data": None})()


class TableClient:
    def __init__(self, client: httpx.Client, name: str):
        self._client = client
        self._table = name

    def insert(self, row: dict) -> InsertBuilder:
        return InsertBuilder(self._client, self._table, row)

    def select(self, *columns) -> SelectBuilder:
        return SelectBuilder(self._client, self._table, ",".join(columns) if columns else "*")

    def upsert(self, row: dict, on_conflict: str) -> UpsertBuilder:
        return UpsertBuilder(self._client, self._table, row, on_conflict)


class SupabaseClient:
    def __init__(self, base_url: str, service_key: str, timeout: float = 30.0):
        root = (base_url or "").rstrip("/")
        if not root:
            raise ValueError("Supabase URL is required")
        if not service_key:
            raise ValueError("Supabase service key is required")

        self._client = httpx.Client(
            base_url=f"{root}/rest/v1",
            headers={
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            timeout=timeout,
        )

    def table(self, name: str) -> TableClient:
        return TableClient(self._client, name)


def create_client(url: str, key: str) -> SupabaseClient:
    return SupabaseClient(url, key)
