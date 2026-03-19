from __future__ import annotations

import asyncio

_CLUSTER_RUN_LOCK = asyncio.Lock()


def get_cluster_run_lock() -> asyncio.Lock:
    """Return the shared cluster queue lock used by long-running cluster jobs."""
    return _CLUSTER_RUN_LOCK
