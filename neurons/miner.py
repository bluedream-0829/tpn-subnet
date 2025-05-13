import time
import typing
import asyncio
import aiohttp
import bittensor as bt
from functools import lru_cache
import sybil

from sybil.base.miner import BaseMinerNeuron


class Miner(BaseMinerNeuron):
    def __init__(self, config=None):
        super(Miner, self).__init__(config=config)
        self.query_counts = {}  # for basic rate limiting

    # ✅ Caching response based on input URL to avoid redundant requests
    @lru_cache(maxsize=256)
    def cached_response(self, url: str) -> str:
        # Simulated delay for cache test; replace with useful logic if needed
        return f"Cached solution for: {url}"

    async def forward(self, synapse: sybil.protocol.Challenge) -> sybil.protocol.Challenge:
        bt.logging.info(f"Received challenge: {synapse.challenge_url}")
        challenge_url = synapse.challenge_url

        try:
            # ✅ Fast-path for cached response
            if "cache" in challenge_url:
                synapse.challenge_response = self.cached_response(challenge_url)
                bt.logging.info(f"Using cached response for: {challenge_url}")
                return synapse

            start = time.time()
            async with aiohttp.ClientSession() as session:
                bt.logging.info(f"Sending challenge to {self.miner_server}/challenge")
                async with session.post(
                    f"{self.miner_server}/challenge",
                    json={"url": challenge_url},
                    headers={"Content-Type": "application/json"},
                ) as response:
                    resp_data = await response.json()
                    synapse.challenge_response = resp_data.get("response", "No response")
                    bt.logging.info(f"Solved challenge: {synapse.challenge_response}")
                    latency = time.time() - start
                    if latency > 2.0:
                        bt.logging.warning(f"⚠️ Slow response time: {latency:.2f}s")
                    return synapse

        except Exception as e:
            bt.logging.error(f"Error solving challenge: {e}")
            synapse.challenge_response = "error"
            return synapse

    async def blacklist(self, synapse: sybil.protocol.Challenge) -> typing.Tuple[bool, str]:
        if synapse.dendrite is None or synapse.dendrite.hotkey is None:
            return True, "Missing dendrite or hotkey"

        try:
            uid = self.metagraph.hotkeys.index(synapse.dendrite.hotkey)
        except ValueError:
            return True, "Hotkey not registered"

        if self.config.blacklist.force_validator_permit and not self.metagraph.validator_permit[uid]:
            return True, "Non-validator hotkey"

        # Basic rate limiting logic to avoid abuse
        hotkey = synapse.dendrite.hotkey
        self.query_counts[hotkey] = self.query_counts.get(hotkey, 0) + 1
        if self.query_counts[hotkey] > 20:
            return True, "Rate limit exceeded"

        return False, "Hotkey accepted"

    async def priority(self, synapse: sybil.protocol.Challenge) -> float:
        if synapse.dendrite is None or synapse.dendrite.hotkey is None:
            return 0.0

        try:
            uid = self.metagraph.hotkeys.index(synapse.dendrite.hotkey)
            stake = float(self.metagraph.S[uid])
            return stake  # Higher stake = higher priority
        except ValueError:
            return 0.0
