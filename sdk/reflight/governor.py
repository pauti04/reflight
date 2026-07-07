"""The cost governor: hard budgets, the loop circuit breaker, and a tool-call
cache. It lives inside the recorder's request path, so enforcement costs
nothing extra — every LLM call already flows through us.

A kill is not an exception swallowed somewhere: it's recorded as an error
event with the reason, the run ends with status "killed", and THEN the
GovernorKill propagates to the agent. The flight recorder captures its own
intervention.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class GovernorKill(Exception):
    """The governor stopped the run. str(exc) is the recorded reason."""


@dataclass
class Governor:
    max_cost_usd: float | None = None
    max_total_tokens: int | None = None  # input + output across the run
    max_llm_calls: int | None = None
    loop_breaker: int | None = None  # allow N consecutive identical tool calls, kill the N+1th
    cache_tool_calls: bool = False

    llm_calls: int = field(default=0, init=False)
    cache_hits: int = field(default=0, init=False)
    cache_misses: int = field(default=0, init=False)
    _streak_key: tuple | None = field(default=None, init=False)
    _streak: int = field(default=0, init=False)
    _cache: dict = field(default_factory=dict, init=False)

    # -- llm budget ----------------------------------------------------------------

    def before_llm(self, session) -> None:
        if self.max_llm_calls is not None and self.llm_calls >= self.max_llm_calls:
            raise GovernorKill(f"llm-call limit reached ({self.max_llm_calls} calls)")
        spent = getattr(session, "total_cost_usd", 0.0) or 0.0
        if self.max_cost_usd is not None and spent >= self.max_cost_usd:
            raise GovernorKill(
                f"budget exceeded: ${spent:.4f} spent ≥ ${self.max_cost_usd:.2f} cap"
            )
        total_tokens = session.total_input_tokens + session.total_output_tokens
        if self.max_total_tokens is not None and total_tokens >= self.max_total_tokens:
            raise GovernorKill(
                f"token budget exceeded: {total_tokens} ≥ {self.max_total_tokens} cap"
            )
        self.llm_calls += 1

    # -- tool circuit breaker + cache -------------------------------------------------

    def before_tool(self, name: str, input_hash: str) -> tuple[str, bool] | None:
        """Raises on a loop; returns a cached (result, is_error) on a cache hit."""
        key = (name, input_hash)
        if key == self._streak_key:
            self._streak += 1
        else:
            self._streak_key, self._streak = key, 1
        if self.loop_breaker is not None and self._streak > self.loop_breaker:
            raise GovernorKill(
                f"loop circuit breaker: {name} called {self._streak} consecutive times "
                "with identical arguments"
            )
        if self.cache_tool_calls and key in self._cache:
            self.cache_hits += 1
            return self._cache[key]
        self.cache_misses += 1
        return None

    def after_tool(self, name: str, input_hash: str, result: str, is_error: bool) -> None:
        if self.cache_tool_calls:
            self._cache[(name, input_hash)] = (result, is_error)

    def stats(self) -> dict:
        return {
            "llm_calls": self.llm_calls,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_hit_rate": (
                self.cache_hits / (self.cache_hits + self.cache_misses)
                if (self.cache_hits + self.cache_misses)
                else 0.0
            ),
        }
