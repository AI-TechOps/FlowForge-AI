"""LLM-as-judge (spec 06 §2, D5, D19 decision 1).

A model does not grade its own homework. The judge runs on a different model
family from triage — `qwen2.5:7b` against `llama3.1:8b` — because two prompts
on one model share its blind spots, which is exactly what an independent score
is supposed to detect. `Settings` refuses a judge equal to the triage model, so
the guarantee is a config error rather than a convention.

Output is validated against a Pydantic schema like every other structured model
call (a project-wide rule): a judge that returns prose instead of scores is a
failed judgement, not a silent zero.
"""

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings, get_settings
from app.eval.prompts import JUDGE_VERSION, SYSTEM, build_prompt
from app.llm.provider import get_provider

logger = logging.getLogger(__name__)

__all__ = ["JUDGE_VERSION", "JudgeScore", "judge_result"]


class JudgeScore(BaseModel):
    """One judgement. Bounded integers, so an out-of-range score is a
    validation error rather than an outlier that quietly drags a mean."""

    model_config = ConfigDict(extra="forbid")

    resolution_quality: int = Field(ge=1, le=5)
    citation_support: int = Field(ge=1, le=5)
    rationale: str = Field(default="", max_length=1000)


async def judge_result(
    ticket: dict[str, Any],
    actual: dict[str, Any] | None,
    evidence: list[dict[str, Any]] | None,
    settings: Settings | None = None,
) -> JudgeScore | None:
    """Score one triage result, or None if it cannot be judged.

    None rather than a low score when there is nothing to judge — a run that
    produced no resolution has not written a *bad* answer, it has written no
    answer, and folding that in as a 1 would blame the judge's subject for the
    pipeline's failure. `summarize` excludes None from the judge means, while
    the deterministic scores still count that ticket as incorrect, so the
    failure is visible in accuracy where it belongs.
    """
    settings = settings or get_settings()
    resolution = (actual or {}).get("recommended_resolution")
    if not resolution:
        return None

    provider = get_provider(settings, chat_model=settings.judge_model)
    prompt = build_prompt(
        ticket_title=ticket.get("title", ""),
        ticket_description=ticket.get("description", ""),
        recommended_resolution=resolution,
        citations=(actual or {}).get("citations") or [],
        evidence=evidence or [],
    )

    try:
        completion = await provider.complete_structured(
            prompt, JudgeScore.model_json_schema(), system=SYSTEM
        )
        return JudgeScore.model_validate_json(completion.raw)
    except Exception:  # noqa: BLE001 - a failed judgement must not fail the batch
        # Deliberately swallowed. The judge is one signal among several, and a
        # judge outage should cost the batch its judge means, not its
        # deterministic accuracy — which is the number the regression table
        # actually depends on (G5.4).
        logger.warning("judge scoring failed; result recorded without judge scores", exc_info=True)
        return None
