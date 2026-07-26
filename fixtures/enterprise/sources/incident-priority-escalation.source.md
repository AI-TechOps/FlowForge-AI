---
doc_id: MD-IT-002
title: Incident Priority & Escalation Guidelines
version: "1.0"
effective_date: 2026-07-01
owner_team: Service Desk
applies_to: All Meridian Dynamics IT support tickets and support teams
review_cadence: Semiannual
---

# MD-IT-002 - Incident Priority & Escalation Guidelines

## 1. Purpose

This guideline defines a consistent P1–P4 priority from business impact and
urgency for every Meridian Dynamics IT ticket. It prevents priority from being
set by capitalization, job title, or an unsupported statement that an issue is
“urgent.” The guideline also names response targets, owning-team handoffs, and
escalation thresholds. It applies after the ticket category is understood; the
priority expresses when support must act, not which team possesses the relevant
expertise. When evidence is incomplete, Service Desk records what is known,
chooses the less severe supported priority, and immediately asks for the missing
impact details.

## 2. Scope

The matrix applies to incidents and requests involving network access, accounts,
hardware, software licensing, email and collaboration, security incidents, and
general inquiries. It applies during business hours and after hours; response
targets are elapsed time for P1 and P2 and business time for P3 and P4. Safety,
confirmed compromise, or active data exposure may require emergency procedures
beyond this IT matrix. Planned maintenance that follows an approved change is
not an incident unless service exceeds its communicated window or unexpected
impact occurs. Human-resources, legal, finance, and facilities matters are
outside this taxonomy unless an IT service or security control is directly
affected.

## 3. Definitions

**Impact** is the breadth and business consequence of the issue: one user, 2–9
users, 10 or more users, an entire location, or a critical service. **Urgency**
is how quickly harm grows if support waits. `critical` means active severe harm,
confirmed compromise, or no service for a critical operation. `high` means work
is blocked or a confirmed near-term business event is at risk. `medium` means
work is degraded but harm is contained or a workaround exists. `low` means a
planned request, question, or issue with no current business interruption.
**Priority** is the response order: P1 is highest and P4 is lowest. **Initial
response** means a qualified analyst acknowledges, validates impact, and begins
or coordinates action; it does not promise final resolution.

## 4. Policy / Procedure

Assign P1 when an outage affects 10 or more users and stops a critical business
operation with no workaround; when a critical business service is unavailable;
or when active compromise, active data exposure, or dangerous hardware is
confirmed. P1 requires immediate paging and continuous coordination.

Assign P2 when 2–9 users are blocked with no reasonable workaround; one user is
blocked from a confirmed time-critical customer or operational event; or a
security incident is suspected but active compromise is not yet confirmed. P2
requires an initial response within thirty minutes.

Assign P3 when one user is blocked without an immediate deadline, a limited
group is degraded with a workable alternative, or a standard repair is needed.
P3 requires an initial response within four business hours.

Assign P4 to planned access, hardware, software, and license requests; routine
questions; cosmetic defects; and problems with an effective workaround and no
near-term impact. P4 requires an initial response within one business day.
Analysts record affected users, service, workaround, deadline, and evidence.
Priority is reassessed whenever any of these facts changes.

## 5. Priority & escalation

Service Desk owns initial triage and the priority record. IT Infrastructure owns
network, VPN, Wi-Fi, server, and DNS incidents. IT Security owns account-control,
MFA, phishing, and security incidents. Workplace IT owns laptops, peripherals,
printers, and meeting-room hardware. Business Applications owns email,
collaboration, ERP, SaaS, and licensing. Service Desk remains the `general_inquiry`
fallback when evidence does not support a specialist category.

P1 is paged immediately to the owning team and incident lead, with updates at
least every thirty minutes. P2 is accepted by the owning team within thirty
minutes and escalated to its lead if unacknowledged after fifteen minutes. P3
and P4 follow queue targets but escalate when impact increases or the response
target is missed. A requester’s executive title never changes priority by
itself. Conflicting signals are resolved using observable impact, urgency,
workaround, and security evidence, and the rationale is recorded.

## 6. Related documents

MD-IT-001 applies the matrix to MeridianConnect VPN. MD-IT-003 and MD-IT-004
apply it to account and MFA recovery. MD-IT-005 applies it to device and room
hardware. MD-IT-006 and MD-IT-007 apply it to licensing and collaboration.
MD-IT-008 defines security reporting and makes confirmed compromise a P1.
MD-IT-009 and MD-IT-010 apply it to workforce transitions and remote work.

## 7. Revision history

Version 1.0 became effective on 2026-07-01. It establishes the 10-user P1
threshold, P2 time-critical single-user rule, response targets, closed team
ownership, evidence requirements, and the rule that observable impact overrides
unsupported urgency language or requester seniority.
