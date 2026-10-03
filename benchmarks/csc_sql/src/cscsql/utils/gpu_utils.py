"""Wait for a finished vLLM stage to hand its GPU memory back.

Every CSC-SQL stage (table link, generate, merge, and the cluster-filter
pre-pass) is its own vLLM process. Under WSL the driver returns a dead
process's VRAM only after a delay of several seconds, and a stage started in
that window sizes its KV cache against memory still counted as in use: vLLM
then aborts with "No available memory for the cache blocks". Stages that do
CPU work in between (SQL execution, voting) usually outlast the delay; the
cluster-filter path launches the next stage almost at once and does not.
"""

import shutil
import subprocess
import time


def gpu_used_mib(devices="0"):
    """Memory in use on the first visible GPU, in MiB, or None if unknown."""
    if shutil.which("nvidia-smi") is None:
        return None
    dev = str(devices).split(",")[0].strip() or "0"
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits", "-i", dev],
            capture_output=True, text=True, timeout=20)
        return int(out.stdout.strip().splitlines()[0])
    except Exception:
        return None


def wait_for_gpu_release(before_mib, devices="0", timeout_s=120, slack_mib=512, poll_s=2.0):
    """Block until GPU memory in use is back within ``slack_mib`` of ``before_mib``
    (its level before the stage started), or ``timeout_s`` passes."""
    if before_mib is None:
        return
    start = time.monotonic()
    while time.monotonic() - start < timeout_s:
        used = gpu_used_mib(devices)
        if used is None or used <= before_mib + slack_mib:
            return
        time.sleep(poll_s)
    print(f"WARNING: GPU memory still {gpu_used_mib(devices)} MiB after {timeout_s}s "
          f"(was {before_mib} MiB before the stage); starting the next stage anyway")


def release_torch_gpu(*objs):
    """Drop references to GPU models (e.g. the BGE retriever) and return the
    cached blocks to the driver, so a vLLM engine started afterwards by this
    process or its children budgets against free memory rather than memory a
    finished encoder still holds."""
    import gc
    for o in objs:
        del o
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
