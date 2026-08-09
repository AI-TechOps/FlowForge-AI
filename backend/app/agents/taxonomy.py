"""Triage taxonomy — the runtime source of truth for classification values (D16).

`fixtures/enterprise/taxonomy.json` mirrors this module for the demo corpus and
eval labels; a Codex-owned parity test asserts the two agree. The runtime copy
is authoritative because `backend/app/` may never import from `fixtures/`
(D6, enforced by scripts/check_runtime_isolation.py).

Changing any value here is a breaking change for the eval seed labels: bump
AGENT_VERSION and re-run the eval batch.
"""

import enum


class Category(enum.StrEnum):
    network_access = "network_access"
    account_access = "account_access"
    hardware = "hardware"
    software_licensing = "software_licensing"
    email_collaboration = "email_collaboration"
    security_incident = "security_incident"
    general_inquiry = "general_inquiry"


class Urgency(enum.StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class Priority(enum.StrEnum):
    p1 = "P1"
    p2 = "P2"
    p3 = "P3"
    p4 = "P4"


class Team(enum.StrEnum):
    service_desk = "Service Desk"
    it_infrastructure = "IT Infrastructure"
    it_security = "IT Security"
    workplace_it = "Workplace IT"
    business_applications = "Business Applications"
