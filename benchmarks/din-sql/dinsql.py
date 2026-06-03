"""DIN-SQL CLI entry point.

Run with::

    python dinsql.py --dataset spider --model gpt-4.1-mini
    python dinsql.py --dataset bird --history --sample 50 --rename --view

See ``python dinsql.py --help`` for the full flag set, or the README.
"""

from __future__ import annotations

import logging
import os
import sys

# Make ``_common`` importable when running this script directly from din-sql/.
_BENCH_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _BENCH_DIR not in sys.path:
    sys.path.insert(0, _BENCH_DIR)

# The folder name contains a hyphen, which is not a valid Python module name;
# import the pipeline via a fully-resolved path when running this file as a script.
if __package__ in (None, ""):
    import importlib.util
    _PIPELINE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline.py")
    _spec = importlib.util.spec_from_file_location("_dinsql_pipeline", _PIPELINE_PATH)
    _pipeline_mod = importlib.util.module_from_spec(_spec)

    # Load sibling modules into a synthetic package so relative imports inside
    # pipeline.py (``from . import prompts``, ``from .config import ...``) resolve.
    import types
    _PKG_NAME = "_dinsql_pkg"
    _pkg = types.ModuleType(_PKG_NAME)
    _pkg.__path__ = [os.path.dirname(os.path.abspath(__file__))]
    sys.modules[_PKG_NAME] = _pkg
    for _modname in ("prompts", "config", "pipeline"):
        _modpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{_modname}.py")
        _spec_m = importlib.util.spec_from_file_location(f"{_PKG_NAME}.{_modname}", _modpath)
        _mod = importlib.util.module_from_spec(_spec_m)
        _mod.__package__ = _PKG_NAME
        sys.modules[f"{_PKG_NAME}.{_modname}"] = _mod
        _spec_m.loader.exec_module(_mod)
        setattr(_pkg, _modname, _mod)
    run = sys.modules[f"{_PKG_NAME}.pipeline"].run
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
