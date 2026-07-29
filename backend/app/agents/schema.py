"""The structured triage result — the only shape the agent may emit.

Matches the MVP definition's JSON exactly (specs/00-mvp-definition.md, step 3).
Raw model text is never trusted for routing decisions: everything the graph
acts on passes through this schema first.
"""

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.agents.taxonomy import Category, Priority, Team, Urgency


class Citation(BaseModel):
    """A claim tied to the retrieved chunk that supports it.

    A citation is only *valid* if its chunk_id was actually retrieved during
    this run (checked in the grounding gate) — a model naming a plausible
    document is not evidence.
    """

    model_config = ConfigDict(extra="forbid")

    chunk_id: uuid.UUID
    document_title: str
    page: int | None = None
    section: str | None = None
    claim: str = Field(min_length=1, max_length=1000)


class TriageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=2000)
    category: Category
    urgency: Urgency
    recommended_team: Team
    suggested_priority: Priority
    recommended_resolution: str = Field(min_length=1, max_length=5000)
    confidence: float = Field(ge=0.0, le=1.0)
    # Informational only. The graph derives the real value from the proposed
    # tool's gating (D16 / spec 03 §5) — the model never controls this.
    requires_approval: bool = True
    citations: list[Citation] = Field(default_factory=list)
