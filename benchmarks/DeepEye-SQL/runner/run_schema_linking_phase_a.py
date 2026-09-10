"""opt2 schema linking, phase a.

Phase A: direct + value linkers, then derive and store the cluster match.
         Few-shot preparation runs AFTER this, so it can see the cluster schema,
         the join paths and a cluster-restricted pool -- none of which exist
         until the direct linker has run.
Phase B: the reversed linker only, reusing phase A's direct/value results
         verbatim (no resampling), against the pruned cluster schema and
         whatever prep selected.

Both phases read and write the same schema-linking snapshot, so phase B resumes
from phase A rather than redoing it.
"""

import sys
sys.path.append(".")

from app.config import get_config
from app.logger import configure_logger
from app.pipeline import SchemaLinkingRunner

if __name__ == "__main__":
    app_config = get_config()
    configure_logger(app_config.logger_config.print_level)
    runner = SchemaLinkingRunner.from_config(app_config)
    runner._ldd_phase = "a"
    runner.run()
