import logging
import json
import os
from typing import Dict, Any
from .throttling import BoundedTokenBucket, HostCircuitBreaker

logger = logging.getLogger(__name__)

class StateManager:
    def __init__(self, state_file: str = "drizzler_state.json"):
        self.state_file = state_file

    def save_state(self, buckets: Dict[str, BoundedTokenBucket], breakers: Dict[str, HostCircuitBreaker]):
        state = {
            "buckets": {name: bucket.to_dict() for name, bucket in buckets.items()},
            "breakers": {name: breaker.to_dict() for name, breaker in breakers.items()},
        }
        try:
            with open(self.state_file, "w") as f:
                json.dump(state, f, indent=2)
            logger.info(f"State saved to {self.state_file}")
        except Exception as e:
            logger.error(f"Failed to save state: {e}")

    def load_state(self, bucket_config, breaker_config) -> tuple:
        if not os.path.exists(self.state_file):
            logger.info("No state file found. Starting fresh.")
            return {}, {}
        try:
            with open(self.state_file, "r") as f:
                state = json.load(f)
            buckets = {
                name: BoundedTokenBucket.from_dict(data, **bucket_config(name))
                for name, data in state.get("buckets", {}).items()
            }
            breakers = {
                name: HostCircuitBreaker.from_dict(data, **breaker_config(name))
                for name, data in state.get("breakers", {}).items()
            }
            logger.info(f"Loaded state for {len(buckets)} buckets and {len(breakers)} breakers")
            return buckets, breakers
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
            return {}, {}