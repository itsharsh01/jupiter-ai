from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from agent.audit import kg_context
from agent.audit.generation_agent import run_strategy_generation_agent

logger = logging.getLogger(__name__)

StrategyFetcher = Callable[[str], list[dict[str, Any]]]

STRATEGIES: list[tuple[str, StrategyFetcher]] = [
    ("governance", kg_context.fetch_governance_context),
    ("ai_risk", kg_context.fetch_ai_risk_context),
    ("tool_abuse", kg_context.fetch_tool_abuse_context),
    ("data_leakage", kg_context.fetch_data_leakage_context),
    ("control_bypass", kg_context.fetch_control_bypass_context),
]


@dataclass
class GenerationResult:
    test_cases: list[dict[str, Any]] = field(default_factory=list)
    strategies_generated: list[str] = field(default_factory=list)
    strategies_skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    strategy_confidence: dict[str, float] = field(default_factory=dict)


def _generate_strategy(
    strategy: str,
    fetcher: StrategyFetcher,
    customer_id: str,
) -> tuple[list[dict[str, Any]], str | None, float, int]:
    context = fetcher(customer_id)
    if not context:
        return [], f"No graph context for strategy '{strategy}'", 0.0, 0

    agent_result = run_strategy_generation_agent(strategy, context)
    if agent_result.warning and not agent_result.test_cases:
        return [], agent_result.warning, 0.0, agent_result.iterations

    warning = agent_result.warning
    return (
        agent_result.test_cases,
        warning,
        agent_result.confidence,
        agent_result.iterations,
    )


def generate_all_strategies(customer_id: str) -> GenerationResult:
    result = GenerationResult()

    for strategy, fetcher in STRATEGIES:
        try:
            cases, warning, confidence, iterations = _generate_strategy(
                strategy, fetcher, customer_id
            )
        except Exception as exc:
            logger.exception("Strategy %s failed", strategy)
            result.warnings.append(f"{strategy}: {exc}")
            result.strategies_skipped.append(strategy)
            continue

        if not cases:
            logger.info("Skipping strategy %s: %s", strategy, warning)
            if warning:
                result.warnings.append(warning)
            result.strategies_skipped.append(strategy)
            continue

        result.test_cases.extend(cases)
        result.strategies_generated.append(strategy)
        result.strategy_confidence[strategy] = confidence
        if warning:
            result.warnings.append(warning)
        logger.info(
            "Strategy %s generated %s cases (confidence=%.2f, iterations=%s)",
            strategy,
            len(cases),
            confidence,
            iterations,
        )

    return result
