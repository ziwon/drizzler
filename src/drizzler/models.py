from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Callable, Any

@dataclass
class Stats:
    total: int
    success: int
    errors: int
    mean: Optional[float]
    std: Optional[float]
    p50: Optional[float]
    p90: Optional[float]
    p95: Optional[float]
    p99: Optional[float]
    min: Optional[float]
    max: Optional[float]
    error_rate: float
    status_counts: Dict[int, int]

# Timeline: worker_id -> list of (start, end, host, status)
TimelineType = Dict[int, List[Tuple[float, float, str, Optional[int]]]]

# Metrics callback: callable accepting stats dict
MetricsCallback = Callable[[Dict[str, Any]], None]