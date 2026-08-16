"""Judge rubric and prompt, versioned (spec 06 §2).

`JUDGE_VERSION` is stamped on every batch alongside the judge model. A rubric
edit changes what the scores mean, so it invalidates comparison against earlier
batches exactly as a prompt edit invalidates triage comparison — changing
either MUST bump the version, or the regression table silently compares two
different questions.

The rubric is anchored: each point on the 1-5 scale says what it describes,
rather than leaving the model to invent its own scale. Unanchored rubrics drift
between calls and between models, which is the main source of judge variance
this spec's Risks section warns about.
"""

JUDGE_VERSION = "judge-v1"

RESOLUTION_RUBRIC = """\
5 - Correct and complete. Follows the cited policy, addresses the specific
    problem in the ticket, and a support engineer could act on it as written.
4 - Correct but thin. Right direction, missing a step or a caveat.
3 - Partially correct. Addresses part of the problem, or is generic advice that
    happens to fit.
2 - Mostly wrong. Misreads the problem or contradicts the cited policy in a way
    that would waste the requester's time.
1 - Wrong or harmful. Would make the situation worse, or invents a procedure
    that does not appear in the evidence."""

CITATION_RUBRIC = """\
5 - Every claim that needs support has a citation, and each cited passage
    genuinely says what the answer claims it says.
4 - Support is present but one claim leans further than its citation goes.
3 - Cited passages are topically related but do not establish the specific
    claim.
2 - Citations are largely decorative; the answer would read the same without
    them.
1 - Citations contradict the answer, or point at passages about something else."""

SYSTEM = (
    "You are evaluating another system's support-ticket triage. Score strictly "
    "against the rubric and the evidence provided. Judge only what is written: "
    "do not credit an answer for being plausible if the evidence does not "
    "support it, and do not penalise it for omitting something the evidence "
    "does not contain. Reply with JSON only."
)


def build_prompt(
    ticket_title: str,
    ticket_description: str,
    recommended_resolution: str,
    citations: list[dict],
    evidence: list[dict],
) -> str:
    """Assemble the judge prompt.

    Evidence text is included so citation-support can be judged rather than
    guessed — asking whether a citation supports a claim without showing the
    cited passage would measure the judge's imagination.

    The expected labels are deliberately NOT included. The judge scores
    resolution quality and citation support; the labelled fields are scored
    deterministically in `scoring.py`, and showing the answer key here would
    let the judge grade agreement-with-the-key instead of quality.
    """
    cited_ids = {str(citation.get("chunk_id")) for citation in citations or []}
    passages = [
        f"[{item.get('chunk_id')}] {item.get('document_title')}\n{item.get('text', '')}"
        for item in (evidence or [])
        if str(item.get("chunk_id")) in cited_ids
    ] or ["(the answer cited nothing that was retrieved)"]

    return f"""\
TICKET
{ticket_title}
{ticket_description}

PROPOSED RESOLUTION
{recommended_resolution}

CITED EVIDENCE
{chr(10).join(passages)}

RUBRIC - resolution_quality
{RESOLUTION_RUBRIC}

RUBRIC - citation_support
{CITATION_RUBRIC}

Return JSON with integer fields `resolution_quality` (1-5),
`citation_support` (1-5), and a one-sentence `rationale`."""
