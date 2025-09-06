from typing import Dict, List, Optional, Tuple

def render_latency_histogram(latencies: List[float], bins: int = 20) -> str:
    if not latencies:
        return "No latency data."
    lo, hi = min(latencies), max(latencies)
    if hi <= lo:
        return f"Histogram: single value {lo:.4f}s"


    width = 40
    counts = [0] * bins
    for x in latencies:
        j = int((x - lo) / (hi - lo) * bins)
        if j == bins:
            j -= 1
        counts[j] += 1


    peak = max(counts)
    lines = []
    for i, c in enumerate(counts):
        left = lo + (hi - lo) * (i / bins)
        right = lo + (hi - lo) * ((i + 1) / bins)
        bar = "#" * max(1, int((c / peak) * width)) if peak else ""
        lines.append(f"{left:.3f}s – {right:.3f}s | {bar} ({c})")
    return "Latency Histogram\n" + "\n".join(lines)


def render_timeline(
    timeline: Dict[int, List[Tuple[float, float, str, Optional[int]]]],
    width: int = 80,
) -> str:
    if not timeline:
        return "No timeline data."


    max_t = 0.0
    for segs in timeline.values():
        for _, end_rel, _, _ in segs:
            if end_rel > max_t:
                max_t = end_rel
        if max_t <= 0:
            max_t = 1.0


    lines = ["Request Timeline (relative seconds)"]
    for worker_id in sorted(timeline.keys()):
        buf = [" "] * width
        for start_rel, end_rel, _host, _status in timeline[worker_id]:
            a = int(start_rel / max_t * (width - 1))
            b = int(end_rel / max_t * (width - 1))
            a, b = max(0, a), max(a, b)
            for k in range(a, b + 1):
                buf[k] = "="
        lines.append(f"W{worker_id:02d} |{''.join(buf)}|")
    lines.append(f"0s{' '*(width-6)}~ {max_t:.2f}s")
    return "\n".join(lines)