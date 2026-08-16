"""G5.2 — judge sanity.

Three claims, and they are not equally testable offline:

1. judge model != triage model — asserted in config validation, so a
   misconfigured stack refuses to start rather than recording a batch in which
   a model graded its own output (D5).
2. judge output validates against the rubric schema — a judge that replies with
   prose is a failed judgement, never a silent zero.
3. a deliberately-wrong resolution scores lower than a correct one.

Claim 3 is a **real-model gate, opt-in like G2.4** (D19 decision 3): it needs
actual semantics, and the fake provider is deterministic and semantically
blind. CI asserts 1 and 2, which is what a fake can honestly prove. A "judge
mode" in the fake provider was rejected as proof of wiring dressed up as proof
of judgement, so this file refuses to run the canary against a fake stack.
"""

from __future__ import annotations

import asyncio
import inspect
import os

import pytest
from pydantic import ValidationError

from .conftest import runtime_module, truthy

config = runtime_module("app.config")
judge = runtime_module("app.eval.judge")
judge_prompts = runtime_module("app.eval.prompts")

BASE_SETTINGS = {
    "database_url": "postgresql+asyncpg://gate:gate@localhost:5432/gate",
    "redis_url": "redis://localhost:6379/0",
}

TICKET = {
    "title": "MeridianConnect drops every few minutes",
    "description": (
        "From home, MeridianConnect disconnects about every five minutes. Ordinary "
        "websites still work and my phone hotspot keeps the VPN stable."
    ),
}
EVIDENCE = [
    {
        "chunk_id": "chunk-1",
        "document_title": "MD IT 001 VPN access policy",
        "text": (
            "Section 5: repeated MeridianConnect disconnections are handled by IT "
            "Infrastructure. Confirm the client is on the current build, disable "
            "split tunnelling, and reconnect over a wired network before escalating."
        ),
    }
]
CORRECT = {
    "recommended_resolution": (
        "Confirm the MeridianConnect client is on the current build, disable split "
        "tunnelling and reconnect over a wired network, per section 5; escalate to "
        "IT Infrastructure only if the disconnections continue."
    ),
    "citations": [{"chunk_id": "chunk-1", "claim": "section 5 recovery steps"}],
}
WRONG = {
    "recommended_resolution": (
        "Reset the requester's payroll password and ask Facilities to replace the "
        "office door badge; VPN disconnections are a building access issue."
    ),
    "citations": [{"chunk_id": "chunk-1", "claim": "section 5 recovery steps"}],
}


def test_g5_2_judge_equal_to_triage_is_refused_at_config_load() -> None:
    with pytest.raises(ValidationError) as caught:
        config.Settings(
            **BASE_SETTINGS, triage_model="llama3.1:8b", judge_model="llama3.1:8b"
        )
    assert "JUDGE_MODEL" in str(caught.value)


def test_g5_2_whitespace_does_not_smuggle_the_same_model_past_validation() -> None:
    with pytest.raises(ValidationError):
        config.Settings(
            **BASE_SETTINGS, triage_model="llama3.1:8b", judge_model=" llama3.1:8b "
        )


def test_g5_2_distinct_models_are_accepted_and_are_the_shipped_default() -> None:
    settings = config.Settings(**BASE_SETTINGS)
    assert settings.judge_model != settings.triage_model
    # Different family, not merely a different tag (D19 decision 1): two prompts
    # on one model share its blind spots.
    assert settings.judge_model.split(":")[0] != settings.triage_model.split(":")[0]


@pytest.mark.parametrize(
    "payload",
    [
        '{"resolution_quality": 0, "citation_support": 3, "rationale": "x"}',
        '{"resolution_quality": 6, "citation_support": 3, "rationale": "x"}',
        '{"resolution_quality": 3, "citation_support": 9, "rationale": "x"}',
        '{"resolution_quality": 3}',
        '{"resolution_quality": 3, "citation_support": 3, "verdict": "good"}',
        "The resolution looks broadly reasonable to me.",
        "",
    ],
)
def test_g5_2_out_of_rubric_output_fails_validation(payload: str) -> None:
    """Anything outside the rubric is a failed judgement, not an outlier.

    An unbounded score would quietly drag a mean, and a mean that can be
    dragged by one malformed reply is not a number worth comparing across
    agent versions.
    """
    with pytest.raises(Exception):  # noqa: B017 - pydantic raises several types here
        judge.JudgeScore.model_validate_json(payload)


def test_g5_2_valid_rubric_output_parses() -> None:
    score = judge.JudgeScore.model_validate_json(
        '{"resolution_quality": 4, "citation_support": 5, "rationale": "follows section 5"}'
    )
    assert (score.resolution_quality, score.citation_support) == (4, 5)


def test_g5_2_judge_is_not_called_when_there_is_nothing_to_judge() -> None:
    """No resolution means no judgement, not a score of 1.

    Folding a failed run in as the worst possible answer would blame the
    judge's subject for the pipeline's failure; the deterministic scores
    already count that ticket as incorrect.
    """
    assert asyncio.run(judge.judge_result(TICKET, None, EVIDENCE)) is None
    assert (
        asyncio.run(
            judge.judge_result(TICKET, {"recommended_resolution": ""}, EVIDENCE)
        )
        is None
    )


def test_g5_2_the_prompt_never_shows_the_judge_the_answer_key() -> None:
    prompt = judge_prompts.build_prompt(
        ticket_title=TICKET["title"],
        ticket_description=TICKET["description"],
        recommended_resolution=CORRECT["recommended_resolution"],
        citations=CORRECT["citations"],
        evidence=EVIDENCE,
    )
    # The labelled fields are scored deterministically; showing them here would
    # let the judge grade agreement-with-the-key instead of quality. Checked
    # two ways: the enum values never appear...
    for label in ("network_access", "general_inquiry", "EXPECTED", "answer key"):
        assert label not in prompt, (
            f"the judge prompt contains {label!r}; it would then score "
            "agreement with the answer key rather than quality"
        )
    # ...and there is no parameter through which a caller could pass them.
    parameters = set(inspect.signature(judge_prompts.build_prompt).parameters)
    assert not parameters & {"expected", "labels", "label", "answer_key"}, parameters
    assert judge_prompts.RESOLUTION_RUBRIC in prompt
    assert judge_prompts.CITATION_RUBRIC in prompt
    # The cited passage itself, or citation support is guesswork.
    assert "split tunnelling" in prompt


def test_g5_2_rubric_and_version_move_together() -> None:
    """A rubric edit changes what the scores mean.

    `JUDGE_VERSION` is stamped on every batch beside the judge model, so an
    unversioned rubric change would leave the regression table silently
    comparing two different questions.
    """
    assert judge_prompts.JUDGE_VERSION
    assert judge.JUDGE_VERSION == judge_prompts.JUDGE_VERSION


@pytest.mark.skipif(
    not truthy("PHASE5_RUN_CANARY"),
    reason="canary needs a real judge model; set PHASE5_RUN_CANARY=1 (D19 decision 3)",
)
def test_g5_2_canary_pair_a_wrong_resolution_scores_lower() -> None:
    settings = config.Settings()
    assert settings.llm_provider != "fake", (
        "the canary refuses a fake stack: the fake provider is semantically "
        "blind, so a pass would prove wiring, not judgement (D19 decision 3)"
    )
    good = asyncio.run(judge.judge_result(TICKET, CORRECT, EVIDENCE, settings))
    bad = asyncio.run(judge.judge_result(TICKET, WRONG, EVIDENCE, settings))
    assert good is not None and bad is not None, (
        f"the judge model ({settings.judge_model}) returned nothing to compare; "
        "is it pulled and reachable?"
    )
    assert good.resolution_quality > bad.resolution_quality, (
        f"judge {settings.judge_model} scored a resolution about door badges "
        f"({bad.resolution_quality}) no lower than the documented recovery steps "
        f"({good.resolution_quality}); rationale: {bad.rationale!r}"
    )
    print(
        f"canary: {settings.judge_model} scored correct={good.resolution_quality} "
        f"wrong={bad.resolution_quality} "
        f"(citation support {good.citation_support}/{bad.citation_support})"
    )


def test_g5_2_canary_is_not_silently_skipped_in_a_real_model_run() -> None:
    """A skipped canary must be a choice, not an accident.

    If a run is configured for real models and asks for live gates, the canary
    should be on — the opt-in exists because CI is fake-provider, not because
    the canary is optional when a real model is present.
    """
    if not truthy("PHASE5_REQUIRE_LIVE"):
        pytest.skip("not a live run")
    if os.environ.get("LLM_PROVIDER", "").strip() == "fake":
        pytest.skip("fake provider: the canary is correctly off")
    assert truthy("PHASE5_RUN_CANARY"), (
        "this run uses a real provider, so set PHASE5_RUN_CANARY=1 and let the "
        "canary judge; skipping it here would report an untested judge as green"
    )
