"""
Thin Supabase/PostgREST client using HTTP - avoids heavy supabase-py dependencies
that require pyiceberg (fails to build on Windows/Python 3.14).
"""
import httpx
from config import SUPABASE_URL, SUPABASE_SERVICE_KEY

BASE = f"{SUPABASE_URL.rstrip('/')}/rest/v1"
HEADERS = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal",
}


def _client():
    return httpx.Client(base_url=BASE, headers=HEADERS, timeout=30.0)


class SelectBuilder:
    """Chainable select builder matching supabase .select().eq().gte().lt().execute()"""

    def __init__(self, table: str, columns: str = "*"):
        self._table = table
        self._cols = columns
        self._params: list[tuple[str, str]] = []

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
        with _client() as c:
            r = c.get(f"/{self._table}", params=self._params)
            r.raise_for_status()
            data = r.json()
        return type("Resp", (), {"data": data if data is not None else []})()


class InsertBuilder:
    def __init__(self, table: str, row: dict):
        self._table = table
        self._row = row

    def execute(self):
        with _client() as c:
            c.post(f"/{self._table}", json=self._row)


class UpsertBuilder:
    def __init__(self, table: str, row: dict, on_conflict: str):
        self._table = table
        self._row = row
        self._on_conflict = on_conflict

    def execute(self):
        h = {**HEADERS, "Prefer": "resolution=merge-duplicates"}
        with httpx.Client(base_url=BASE, headers=h, timeout=30.0) as c:
            c.post(f"/{self._table}?on_conflict={self._on_conflict}", json=self._row)


class TableClient:
    """supabase.table()-style API."""

    def __init__(self, name: str):
        self._table = name

    def insert(self, row: dict) -> InsertBuilder:
        return InsertBuilder(self._table, row)

    def select(self, *columns) -> SelectBuilder:
        cols = ",".join(columns) if columns else "*"
        return SelectBuilder(self._table, cols)

    def upsert(self, row: dict, on_conflict: str) -> UpsertBuilder:
        return UpsertBuilder(self._table, row, on_conflict)


class SupabaseClient:
    def table(self, name: str) -> TableClient:
        return TableClient(name)


def create_client(url: str, key: str) -> SupabaseClient:
    """Drop-in for: from supabase import create_client"""
    return SupabaseClient()
