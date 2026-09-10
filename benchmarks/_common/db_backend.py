"""Database backend abstraction — SQLite (default) and MySQL.

Throughout the pipelines a "db path" is an opaque string. Historically it was
always a filesystem path to a ``.sqlite`` file; it may now also be a MySQL
URI, which is what the BEAVER datasets (``dw`` / ``neutron`` / ``nova``) use
because their data only exists in MySQL and their gold SQL is MySQL dialect.

Accepted URI forms::

    mysql://dw                          # database 'dw', credentials from env
    mysql://user:pass@host:3306/dw      # fully explicit
    mysql+pymysql://user:pass@host/dw   # SQLAlchemy-style scheme, same thing

Credentials for the short form are read from ``MYSQL_HOST`` / ``MYSQL_PORT`` /
``MYSQL_USER`` / ``MYSQL_PASSWORD`` (same variable names BEAVER's own
``eval/utils/ex_acc.py`` uses, so one ``.env`` serves both). Process
environment wins; any gaps are filled from ``$MYSQL_ENV_FILE`` and then
``<LDD_ROOT>/.env``.

Callers should not import this module directly for routine work — the public
functions in :mod:`_common.schema`, :mod:`_common.sql_exec`,
:mod:`_common.clusters` and :mod:`_common.evaluate` dispatch on the db string
and keep their original signatures.
"""

from __future__ import annotations

import os
import re
import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import unquote, urlparse

from .paths import LDD_ROOT


_MYSQL_SCHEME_RE = re.compile(r"^mysql(\+\w+)?://", re.I)

# Guard the lazy .env read so concurrent callers don't race on os.environ.
_ENV_LOCK = threading.Lock()
_ENV_LOADED = False


def is_mysql(db: Optional[str]) -> bool:
    """True when ``db`` is a MySQL URI rather than a SQLite file path."""
    return bool(db) and bool(_MYSQL_SCHEME_RE.match(str(db).strip()))


def _load_env_files() -> None:
    """Fill missing ``MYSQL_*`` variables from a ``.env`` file, once per process.

    Never overwrites a variable already present in the process environment.
    """
    global _ENV_LOADED
    with _ENV_LOCK:
        if _ENV_LOADED:
            return
        _ENV_LOADED = True

        candidates = []
        if os.environ.get("MYSQL_ENV_FILE"):
            candidates.append(os.environ["MYSQL_ENV_FILE"])
        candidates.append(os.path.join(LDD_ROOT, ".env"))

        for path in candidates:
            if not path or not os.path.exists(path):
                continue
            try:
                with open(path, encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        key, _, val = line.partition("=")
                        key, val = key.strip(), val.strip().strip('"').strip("'")
                        if key.startswith("MYSQL_") and key not in os.environ:
                            os.environ[key] = val
            except OSError:
                continue


def parse_mysql_uri(db: str) -> Dict[str, Any]:
    """Split a MySQL URI into connect kwargs, filling gaps from the environment."""
    raw = str(db).strip()
    # urlparse needs a scheme it understands for netloc splitting; normalize
    # 'mysql+pymysql' down to 'mysql' first.
    normalized = _MYSQL_SCHEME_RE.sub("mysql://", raw, count=1)
    parsed = urlparse(normalized)

    database = (parsed.path or "").lstrip("/")
    host, port, user, password = parsed.hostname, parsed.port, parsed.username, parsed.password

    # 'mysql://dw' parses as netloc='dw' with an empty path — treat the netloc
    # as the database name when no path component was supplied.
    if not database and parsed.netloc and "@" not in parsed.netloc and ":" not in parsed.netloc:
        database, host = parsed.netloc, None

    if not database:
        raise ValueError(
            f"MySQL URI {db!r} does not name a database. "
            f"Use 'mysql://<dbname>' or 'mysql://user:pass@host:port/<dbname>'."
        )

    _load_env_files()
    return {
        "host": host or os.environ.get("MYSQL_HOST") or "localhost",
        "port": int(port or os.environ.get("MYSQL_PORT") or 3306),
        "user": user or os.environ.get("MYSQL_USER") or "root",
        "password": unquote(password) if password else (os.environ.get("MYSQL_PASSWORD") or ""),
        "database": database,
    }


def connect(db: str, timeout: int = 60):
    """Open a MySQL connection for ``db``. Caller is responsible for closing."""
    try:
        import pymysql
    except ImportError as e:  # pragma: no cover - environment problem
        raise ImportError(
            "MySQL-backed datasets need the 'pymysql' driver: pip install pymysql"
        ) from e

    cfg = parse_mysql_uri(db)
    return pymysql.connect(
        host=cfg["host"], port=cfg["port"], user=cfg["user"],
        password=cfg["password"], database=cfg["database"],
        connect_timeout=timeout, read_timeout=timeout, write_timeout=timeout,
        charset="utf8mb4",
    )


def database_name(db: str) -> str:
    """The schema/database name inside a MySQL URI."""
    return parse_mysql_uri(db)["database"]


# ---------------------------------------------------------------------------
# Introspection
# ---------------------------------------------------------------------------

def list_tables_and_views(db: str) -> List[str]:
    """Sorted names of base tables and views. Mirrors the SQLite helper."""
    conn = connect(db)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = %s ORDER BY table_name",
                (database_name(db),),
            )
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def _name_map(db: str) -> Dict[str, str]:
    """Lowercased name -> as-stored name, for case-insensitive resolution.

    MySQL on Windows runs with ``lower_case_table_names=1``, so tables that
    BEAVER documents as ``FCLT_ORGANIZATION`` are stored as
    ``fclt_organization``. Lookups must not depend on which casing the caller
    happens to hold.
    """
    return {n.lower(): n for n in list_tables_and_views(db)}


# Index/constraint lines that add prompt noise without helping the model.
_INDEX_LINE_RE = re.compile(
    r"^\s*(UNIQUE\s+|FULLTEXT\s+|SPATIAL\s+)?KEY\s+`", re.I
)


def _clean_ddl(ddl: str, display_name: str) -> str:
    """Trim ``SHOW CREATE TABLE`` output down to the SQLite-equivalent shape.

    Drops secondary-index lines and the ``ENGINE=... CHARSET=...`` trailer,
    keeps ``PRIMARY KEY`` and ``FOREIGN KEY`` clauses, and rewrites the table
    name to ``display_name`` so the prompt shows the casing the workload and
    the gold SQL use.
    """
    lines = ddl.split("\n")
    out: List[str] = []

    for line in lines:
        if _INDEX_LINE_RE.match(line):
            continue
        stripped = line.strip()

        if stripped.upper().startswith(("CREATE TABLE", "CREATE VIEW", "CREATE ALGORITHM")):
            out.append(f"CREATE TABLE {display_name} (")
            continue
        if stripped.startswith(")"):
            out.append(")")
            continue
        out.append(line)

    # Removing index lines can leave a trailing comma on the last column line.
    for i in range(len(out) - 1, -1, -1):
        if out[i].strip() == ")":
            continue
        if out[i].rstrip().endswith(","):
            out[i] = out[i].rstrip().rstrip(",")
        break

    return "\n".join(out)


def get_create_statement(db: str, table: str) -> Optional[str]:
    """``CREATE TABLE``-shaped DDL for ``table``, or None when it doesn't exist."""
    actual = _name_map(db).get(table.lower())
    if actual is None:
        return None

    conn = connect(db)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_type FROM information_schema.tables "
                "WHERE table_schema = %s AND table_name = %s",
                (database_name(db), actual),
            )
            row = cur.fetchone()
            is_view = bool(row) and row[0] == "VIEW"

            cur.execute(f"SHOW CREATE {'VIEW' if is_view else 'TABLE'} `{actual}`")
            created = cur.fetchone()
            if not created:
                return None
            # SHOW CREATE TABLE -> (name, ddl); SHOW CREATE VIEW -> (name, ddl, charset, collation)
            return _clean_ddl(created[1], table)
    finally:
        conn.close()


def get_sample_rows(db: str, table: str, num_rows: int) -> Tuple[List[str], List[tuple]]:
    """Return ``(column_names, rows)`` for up to ``num_rows`` rows of ``table``."""
    actual = _name_map(db).get(table.lower())
    if actual is None:
        return [], []

    conn = connect(db)
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM `{actual}` LIMIT {int(num_rows)}")
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description] if cur.description else []
            return cols, list(rows)
    except Exception:
        return [], []
    finally:
        conn.close()


def find_foreign_keys_between_tables(db: str, tables: Sequence[str]) -> List[str]:
    """``A.col=B.col`` strings for declared FKs whose both ends are in ``tables``.

    Output preserves the caller's casing, matching the SQLite implementation.
    """
    if not tables:
        return []

    norm_to_orig: Dict[str, str] = {}
    for t in tables:
        norm_to_orig.setdefault(str(t).lower(), t)

    conn = connect(db)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name, column_name, referenced_table_name, referenced_column_name "
                "FROM information_schema.key_column_usage "
                "WHERE table_schema = %s AND referenced_table_name IS NOT NULL",
                (database_name(db),),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    out = set()
    for from_t, from_c, ref_t, ref_c in rows:
        f_norm, r_norm = str(from_t).lower(), str(ref_t).lower()
        if f_norm in norm_to_orig and r_norm in norm_to_orig:
            out.add(f"{norm_to_orig[f_norm]}.{from_c}={norm_to_orig[r_norm]}.{ref_c}")
    return sorted(out)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def execute(db: str, sql: str, fetch: Any = "all", timeout: int = 60) -> Any:
    """Execute ``sql``. ``fetch`` is ``"all"``, ``"one"``, or an int row cap."""
    conn = connect(db, timeout=timeout)
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            if fetch == "one":
                return cur.fetchone()
            if isinstance(fetch, int) and not isinstance(fetch, bool):
                return cur.fetchmany(fetch)
            return cur.fetchall()
    finally:
        conn.close()
