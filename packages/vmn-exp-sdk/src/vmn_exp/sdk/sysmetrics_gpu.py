#!/usr/bin/env python3
"""The GPU half of :mod:`vmn_exp.sdk.sysmetrics`, over an imported ``pynvml``."""
import logging
import os

_LOGGER = logging.getLogger("vmn_exp.sdk.sysmetrics")

# GPU memory held by this run's process tree (per-process NVML accounting).
GPU_MEM_MB = "sys_gpu_mem_mb"
# Node-level figures over the visible devices, whoever is using them.
GPU_NODE_MEM_MB = "sys_gpu_node_mem_mb"
GPU_NODE_UTIL_PERCENT = "sys_gpu_node_util_percent"

_MB = float(1024 * 1024)


def _visible_handles(pynvml):
    """NVML handles of the devices ``CUDA_VISIBLE_DEVICES`` exposes to the run.

    NVML enumerates every physical device on the node; CUDA only the listed
    ones — by index or by (a unique prefix of) UUID, stopping at the first
    invalid index. Unset means all; empty means none.
    """
    count = pynvml.nvmlDeviceGetCount()
    handles = [pynvml.nvmlDeviceGetHandleByIndex(i) for i in range(count)]
    raw = os.environ.get("CUDA_VISIBLE_DEVICES")
    if raw is None:
        return handles
    visible = []
    for token in (t.strip() for t in raw.split(",")):
        if not token:
            continue
        if token.lstrip("-").isdigit():
            index = int(token)
            if index < 0 or index >= count:
                break
            visible.append(handles[index])
            continue
        match = [h for h in handles if _uuid(pynvml, h).startswith(token)]
        if len(match) != 1:
            break
        visible.append(match[0])
    return visible


def _uuid(pynvml, handle):
    try:
        uuid = pynvml.nvmlDeviceGetUUID(handle)
    except Exception:
        return ""
    return uuid.decode() if isinstance(uuid, bytes) else str(uuid)


def gpu_probe(pynvml, pids=None):
    """GPU memory of the run's processes, plus node memory and utilization.

    *pids* returns the run's process tree each tick. Every NVML query is guarded
    on its own, so a query a device does not support (utilization on MIG, say)
    costs that value, not the whole sample.
    """
    try:
        pynvml.nvmlInit()
        # Handles are stable for the process's lifetime, so resolve them once
        # instead of per device per tick.
        handles = _visible_handles(pynvml)
    except Exception:
        # No driver, no device, a container without /dev/nvidia*: all normal.
        _LOGGER.debug("pynvml is installed but no GPU is reachable", exc_info=True)
        return None
    if not handles:
        return None

    def probe():
        tree = pids() if pids else set()
        used, util, owned = [], [], []
        for h in handles:
            _collect(used, lambda h=h: pynvml.nvmlDeviceGetMemoryInfo(h).used)
            _collect(util, lambda h=h: pynvml.nvmlDeviceGetUtilizationRates(h).gpu)
            _collect(owned, lambda h=h: _tree_gpu_memory(pynvml, h, tree))
        values = {}
        if used:
            values[GPU_NODE_MEM_MB] = round(sum(used) / _MB, 1)
        if util:
            values[GPU_NODE_UTIL_PERCENT] = round(float(sum(util)) / len(util), 1)
        owned = [o for o in owned if o is not None]
        if owned:
            values[GPU_MEM_MB] = round(sum(owned) / _MB, 1)
        return values

    return probe


def _collect(into, query):
    try:
        into.append(query())
    except Exception:
        _LOGGER.debug("An NVML query failed", exc_info=True)


def _tree_gpu_memory(pynvml, handle, tree):
    """Bytes the run's processes hold on *handle*, or None if none is listed.

    None rather than 0 when nothing matches: inside a container NVML reports
    host pids, and "unknown" must not read as "uses no GPU memory".
    """
    matched = [
        p.usedGpuMemory or 0
        for p in pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
        if p.pid in tree
    ]
    return sum(matched) if matched else None
