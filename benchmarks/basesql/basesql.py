"""BaseSQL CLI entry point.

Run with::

    python basesql.py --dataset spider --model gpt-4.1-mini
    python basesql.py --dataset bird --history --sample 50 --rename

See ``python basesql.py --help`` for the full flag set, or the README.
"""

from __future__ import annotations

import logging
import os
import sys

# Make ``_common`` importable when running this script directly from basesql/.
_BENCH_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _BENCH_DIR not in sys.path:
    sys.path.insert(0, _BENCH_DIR)

# Ensure we can resolve ``from . import prompts`` etc. when this file is the
# entry point — re-import the pipeline through the package path.
if __package__ in (None, ""):
    _PKG_PARENT = os.path.dirname(os.path.abspath(__file__))
    if os.path.dirname(_PKG_PARENT) not in sys.path:
        sys.path.insert(0, os.path.dirname(_PKG_PARENT))
    from basesql.pipeline import run  # type: ignore  # noqa: E402
else:
    from .pipeline import run  # noqa: E402


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    run()


if __name__ == "__main__":
    main()
