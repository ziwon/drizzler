from dataclasses import dataclass
from typing import Optional, Any
from collections.abc import Callable


@dataclass
class Stats:
    total: int
    success: int
    errors: int
    mean: float | None
    std: float | None
    p50: float | None
    p90: float | None
    p95: float | None
    p99: float | None
    min: float | None
    max: float | None
    error_rate: float
    status_counts: dict[int, int]


# Timeline: worker_id -> list of (start, end, host, status)
TimelineType = dict[int, list[tuple[float, float, str, Optional[int]]]]

# Metrics callback: callable accepting stats dict
MetricsCallback = Callable[[dict[str, Any]], None]
