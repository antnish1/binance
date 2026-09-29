from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class RiskDecision:
    allowed: bool
    reason: str


class RiskEngine:
    """Phase placeholder. All orders are rejected until explicit risk rules are implemented."""

    async def evaluate(self) -> RiskDecision:
        return RiskDecision(allowed=False, reason="Trading blocked until risk phase is complete")
