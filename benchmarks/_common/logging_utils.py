"""Per-question log helpers."""

from __future__ import annotations

import os


def append_log(log_dir: str, index: int, section: str, body: str) -> None:
    """Append a labeled section to the per-question log file."""
    fp = os.path.join(log_dir, f"q{int(index):04d}.log")
    with open(fp, "a", encoding="utf-8") as f:
        f.write(f"\n===== {section} =====\n")
        f.write(body if body is not None else "")
        f.write("\n")
