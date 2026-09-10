"""Process-wide object allow-list for schema enumeration.

Two reasons this cannot be left to ``sqlite_master.type = 'table'``:

  1. In merged_<ds>.sqlite the RENAMED tables are CREATE VIEWs over the base
     tables, so a type='table' filter returns the 75 ORIGINAL tables no matter
     which arm is running -- the +R arm would silently run on original names.
  2. Every arm must see exactly its own universe and nothing else. One merged
     database holds org tables, renamed tables, org views and renamed views
     side by side; the arm decides which subset exists.

Set once per process (the dataset loader does it), read by load_table_names.
A process runs exactly one arm, so a module-level scope is safe and keeps the
patch to db_utils down to a single function.
"""

from __future__ import annotations

import threading
from typing import Iterable, List, Optional, Set

_lock = threading.RLock()
_scope: Optional[Set[str]] = None       # lower-cased
_scope_ordered: List[str] = []


def set_object_scope(names: Iterable[str]) -> None:
    global _scope, _scope_ordered
    with _lock:
        _scope_ordered = list(names)
        _scope = {n.lower() for n in _scope_ordered}


def clear_object_scope() -> None:
    global _scope, _scope_ordered
    with _lock:
        _scope = None
        _scope_ordered = []


def get_object_scope() -> Optional[Set[str]]:
    return _scope


def scope_is_active() -> bool:
    return _scope is not None


def filter_to_scope(names: Iterable[str]) -> List[str]:
    """Keep only in-scope names, preserving the caller's order."""
    if _scope is None:
        return list(names)
    return [n for n in names if str(n).lower() in _scope]
