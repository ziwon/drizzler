import math
import logging
from collections.abc import Callable
from .models import Stats

logger = logging.getLogger(__name__)


def compute_stats(
    latencies: list[float],
    success_count: int,
    error_count: int,
    status_counts: dict[int, int],
    metrics_callback: Callable[[dict], None] | None = None,
) -> Stats:
    total = success_count + error_count
    logger.debug(
        f"Computing stats: total={total}, success={success_count}, errors={error_count}"
    )

    if not total:
        stats_dict = {
            "total": total,
            "success": success_count,
            "errors": error_count,
            "mean": None,
            "std": None,
            "p50": None,
            "p90": None,
            "p95": None,
            "p99": None,
            "min": None,
            "max": None,
            "error_rate": 0.0,
            "status_counts": dict(status_counts),
        }
        if metrics_callback:
            metrics_callback(stats_dict)
        logger.info("No requests recorded. Returning empty stats.")
        return Stats(**stats_dict)

    n = len(latencies)
    if n == 0:
        stats_dict = {
            "total": total,
            "success": success_count,
            "errors": error_count,
            "mean": None,
            "std": None,
            "p50": None,
            "p90": None,
            "p95": None,
            "p99": None,
            "min": None,
            "max": None,
            "error_rate": error_count / total,
            "status_counts": dict(status_counts),
        }
        if metrics_callback:
            metrics_callback(stats_dict)
        logger.warning("No successful latencies recorded.")
        return Stats(**stats_dict)

    mean = sum(latencies) / n
    sum_sq = sum(x * x for x in latencies)
    std = math.sqrt(max(0.0, (sum_sq / n) - (mean * mean)))

    sl = sorted(latencies)

    def pct(p):
        return sl[max(0, min(n - 1, int(p * (n - 1))))]

    stats_dict = {
        "total": total,
        "success": success_count,
        "errors": error_count,
        "mean": mean,
        "std": std,
        "p50": pct(0.50),
        "p90": pct(0.90),
        "p95": pct(0.95),
        "p99": pct(0.99),
        "min": sl[0],
        "max": sl[-1],
        "error_rate": error_count / total,
        "status_counts": dict(status_counts),
    }

    if metrics_callback:
        metrics_callback(stats_dict)

    logger.info(
        f"Stats computed: success={success_count}, errors={error_count}, "
        f"mean={mean:.3f}s, p95={stats_dict['p95']:.3f}s, error_rate={stats_dict['error_rate'] * 100:.1f}%"
    )

    return Stats(**stats_dict)
