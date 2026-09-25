"""Cost ledger: prices Gemini usage against config.PRICING and enforces a budget cap.

Every Gemini call must be recorded here. Before a call is made, its estimated
cost is checked against the remaining budget (`check_budget`), so a run aborts
before an over-cap call rather than after paying for it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from eventscout.config import PRICING


class BudgetExceededError(RuntimeError):
    """Raised when a call's estimated cost would exceed the run's --max-cost-usd cap."""


@dataclass
class CallRecord:
    stage: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    search_queries: int = 0
    cache_hit: bool = False
    cost_usd: float = 0.0


@dataclass
class CostLedger:
    max_cost_usd: float
    calls: list[CallRecord] = field(default_factory=list)

    @property
    def total_cost_usd(self) -> float:
        return sum(c.cost_usd for c in self.calls)

    @property
    def search_queries_executed(self) -> int:
        return sum(c.search_queries for c in self.calls)

    @property
    def cache_hits(self) -> int:
        return sum(1 for c in self.calls if c.cache_hit)

    def price_tokens(
        self, model: str, input_tokens: int, output_tokens: int, thinking_tokens: int
    ) -> float:
        rates = PRICING["tokens_per_1m_usd"].get(model)
        if not rates:
            return 0.0  # TODO(verify): unpriced model; pricing table not yet filled in
        cost = 0.0
        cost += input_tokens / 1_000_000 * (rates.get("input") or 0)
        cost += output_tokens / 1_000_000 * (rates.get("output") or 0)
        cost += thinking_tokens / 1_000_000 * (rates.get("thinking") or 0)
        return cost

    def price_search_queries(self, count: int) -> float:
        rate = PRICING["grounded_search_per_1k_queries_usd"]
        if rate is None:
            return 0.0  # TODO(verify): pricing not yet confirmed
        return count / 1000 * rate

    def check_budget(self, estimated_additional_cost_usd: float) -> None:
        projected = self.total_cost_usd + estimated_additional_cost_usd
        if projected > self.max_cost_usd:
            raise BudgetExceededError(
                f"Estimated cost ${projected:.4f} would exceed --max-cost-usd cap of "
                f"${self.max_cost_usd:.2f}"
            )

    def record(self, call: CallRecord) -> None:
        self.calls.append(call)

    def summary(self) -> str:
        return (
            f"Cost summary: ${self.total_cost_usd:.4f} spent of ${self.max_cost_usd:.2f} budget\n"
            f"  API calls: {len(self.calls)}  |  cache hits: {self.cache_hits}  |  "
            f"search queries: {self.search_queries_executed}"
        )
