"""Versioned triage prompts.

Prompt text is versioned alongside AGENT_VERSION: changing either invalidates
prior eval batches, so a prompt edit MUST bump AGENT_VERSION and be followed by
a fresh eval run (spec 03 Risks; Phase 5 regression protocol).
"""

from app.agents.taxonomy import Category, Priority, Team, Urgency

AGENT_VERSION = "triage-v1"

TRIAGE_SYSTEM = """You are a support triage analyst for an enterprise IT service desk.

You classify a ticket and recommend a resolution using ONLY the company policy
excerpts provided. You never invent policy. If the excerpts do not cover the
issue, say so in the summary and keep confidence low.

Every substantive claim in your recommendation must be supported by a citation
pointing at one of the supplied chunk_id values. Never cite a chunk_id that is
not in the provided evidence. If no excerpt supports a claim, do not make it.

Respond with a single JSON object matching the required schema. No prose, no
markdown fences."""


def _values(enum_class: type) -> str:
    return ", ".join(member.value for member in enum_class)


def build_triage_prompt(ticket: dict[str, object], evidence: list[dict[str, object]]) -> str:
    evidence_block = (
        "\n\n".join(_format_chunk(index, chunk) for index, chunk in enumerate(evidence, start=1))
        if evidence
        else "(no policy excerpts were retrieved for this ticket)"
    )
    return f"""## Ticket

Title: {ticket.get("title")}
Requester department: {ticket.get("department") or "unspecified"}
Affected service: {ticket.get("service") or "unspecified"}
Existing priority: {ticket.get("priority") or "none"}

Description:
{ticket.get("description")}

## Company policy excerpts (the ONLY permitted evidence)

{evidence_block}

## Allowed values

category: {_values(Category)}
urgency: {_values(Urgency)}
suggested_priority: {_values(Priority)}
recommended_team: {_values(Team)}

## Task

Classify the ticket and recommend a resolution grounded in the excerpts above.
For each citation, use the exact chunk_id of the excerpt that supports the
claim, and state the claim it supports. Set confidence to your genuine
certainty between 0 and 1."""


def _format_chunk(index: int, chunk: dict[str, object]) -> str:
    locator = []
    if chunk.get("page") is not None:
        locator.append(f"page {chunk['page']}")
    if chunk.get("section"):
        locator.append(f"section {chunk['section']}")
    where = f" ({', '.join(locator)})" if locator else ""
    return (
        f"### Excerpt {index}\n"
        f"chunk_id: {chunk.get('chunk_id')}\n"
        f"document: {chunk.get('document_title')} v{chunk.get('document_version')}{where}\n\n"
        f"{chunk.get('text')}"
    )


REPAIR_PROMPT = """Your previous response was rejected: {error}

Return ONLY a corrected JSON object matching the schema. Use the exact allowed
values listed earlier, and cite only chunk_id values from the supplied
excerpts. Do not explain the correction."""
