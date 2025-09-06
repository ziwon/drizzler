import asyncio
import random
import logging
from typing import Optional


logger = logging.getLogger(__name__)

class HostCircuitBreaker:
    def __init__(self, failure_threshold: int = 5, cooldown_s: float = 60.0):
        self.failures = 0
        self.last_failure = 0.0
        self.cooldown_until = 0.0
        self.failure_threshold = failure_threshold
        self.cooldown_s = cooldown_s
        logger.debug(f"Initialized circuit breaker: threshold={failure_threshold}, cooldown={cooldown_s}s")

    def can_attempt(self) -> bool:
        return asyncio.get_event_loop().time() >= self.cooldown_until

    def record_failure(self):
        self.failures += 1
        self.last_failure = asyncio.get_event_loop().time()
        if self.failures >= self.failure_threshold:
            logger.debug(f"Circuit breaker OPEN until {self.cooldown_until:.2f} (now={now:.2f})")
            self.cooldown_until = self.last_failure + self.cooldown_s
            self.failures = 0

    def record_success(self):
        if self.failures > 0:
            logger.debug("Circuit breaker: recorded success, resetting failures")
        self.failures = 0

    def to_dict(self):
        return {
            "failures": self.failures,
            "cooldown_until": self.cooldown_until,
            "last_failure": self.last_failure,
        }

    @classmethod
    def from_dict(cls, data: dict, failure_threshold=5, cooldown_s=60.0):
        obj = cls(failure_threshold, cooldown_s)
        obj.failures = data.get("failures", 0)
        obj.cooldown_until = data.get("cooldown_until", 0.0)
        obj.last_failure = data.get("last_failure", 0.0)
        return obj


class BoundedTokenBucket:
    def __init__(
        self,
        rate_per_sec: float,
        burst: int = 2,
        jitter_ratio: float = 0.15,
        ramp_up_s: float = 10.0,
        name: str = "",
    ) -> None:
        assert rate_per_sec > 0 and burst >= 1
        self.rate = rate_per_sec
        self.burst = burst
        self.q: asyncio.Queue = asyncio.Queue(maxsize=burst)
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self.jitter_ratio = jitter_ratio
        self.ramp_up_s = ramp_up_s
        self._start_t: Optional[float] = None
        self.name = name
        self._cooldown_until: float = 0.0
        self._cooldown_lock = asyncio.Lock()
        logger.debug(f"Created token bucket '{name}': rate={rate_per_sec}, burst={burst}, ramp_up={ramp_up_s}s")

    async def start(self) -> None:
        if self._task is None:
            self._stop.clear()
            self._start_t = asyncio.get_event_loop().time()
            self._task = asyncio.create_task(self._run())
            logger.info(f"Token bucket '{self.name}' started")

    async def stop(self) -> None:
        if self._task:
            self._stop.set()
            await self._task
            self._task = None
            logger.info(f"Token bucket '{self.name}' stopped")

    async def acquire(self) -> None:
        async with self._cooldown_lock:
            cd = self._cooldown_until - asyncio.get_event_loop().time()
        if cd > 0:
            logger.debug(f"Bucket '{self.name}' cooling down for {cd:.2f}s")
            await asyncio.sleep(cd)
        await self.q.get()
        self.q.task_done()
        logger.debug(f"Bucket '{self.name}' acquired token")

    async def cooldown_until(self, wake_ts: float) -> None:
        async with self._cooldown_lock:
            if wake_ts > self._cooldown_until:
                self._cooldown_until = wake_ts
                logger.info(f"Bucket '{self.name}' set cooldown until {wake_ts:.2f}")

    def adjust_rate(self, multiplier: float) -> None:
        """Adaptive rate control"""
        old_rate = self.rate
        self.rate = max(0.1, self.rate * multiplier)
        logger.info(f"Bucket '{self.name}' rate adjusted: {old_rate:.2f} → {self.rate:.2f} (x{multiplier})")

    def _current_rate(self) -> float:
        if self.ramp_up_s <= 0 or self._start_t is None:
            return self.rate
        elapsed = max(0.0, asyncio.get_event_loop().time() - self._start_t)
        base = 0.2 * self.rate
        r = base + (self.rate - base) * min(1.0, elapsed / self.ramp_up_s)
        final_rate = max(0.1, r)
        logger.debug(f"Bucket '{self.name}' current rate: {final_rate:.2f} (elapsed={elapsed:.1f}s)")
        return final_rate

    async def _run(self) -> None:
        logger.debug(f"Bucket '{self.name}' background task started.")  
        try:
            while not self._stop.is_set():
                r = self._current_rate()
                delay = 1.0 / r
                jitter = 1.0 + random.uniform(-self.jitter_ratio, self.jitter_ratio)
                delay *= max(0.2, jitter)
                if self.q.full():
                    await asyncio.sleep(min(0.01, delay))
                    continue
                await self.q.put(None)
                logger.debug(f"Bucket '{self.name}' added token (delay={delay:.3f}s)")
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            logger.debug(f"Bucket '{self.name}' run loop cancelled")
            pass

    def to_dict(self):
        return {
            "rate": self.rate,
            "cooldown_until": self._cooldown_until,
            "start_t_offset": (
                asyncio.get_event_loop().time() - self._start_t if self._start_t else 0
            ),
        }

    @classmethod
    def from_dict(cls, data: dict, **kwargs):
        obj = cls(**kwargs)
        obj.rate = data["rate"]
        obj._cooldown_until = data["cooldown_until"]
        if "start_t_offset" in data and data["start_t_offset"] > 0:
            obj._start_t = asyncio.get_event_loop().time() - data["start_t_offset"]
        return obj