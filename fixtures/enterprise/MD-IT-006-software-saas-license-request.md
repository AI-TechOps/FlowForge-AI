---
doc_id: MD-IT-006
title: Software & SaaS License Request Procedure
version: "1.0"
effective_date: 2026-07-01
owner_team: Business Applications
applies_to: Software installed on Meridian devices and SaaS accessed with company identities
review_cadence: Annual
---

# MD-IT-006 — Software & SaaS License Request Procedure

## 1. Purpose

This procedure governs requests to install software, assign a paid license seat,
start a SaaS subscription, change an application role, or renew an existing
license. It supports tickets such as “I need a license,” “please add me to the
analytics application,” “my subscription expired,” and “can the company buy
this tool?” The procedure makes Business Applications accountable for license
inventory and application access while requiring manager, budget, security, and
data-handling review when appropriate. It prevents shadow IT, duplicate
subscriptions, excessive privileges, and storage of Meridian Dynamics data in
unapproved services.

## 2. Scope

The procedure applies to desktop software on managed devices, browser-based
SaaS, renewals, paid add-ons, application role changes, and license transfers.
It covers both catalog applications and new vendor requests. Free software is
still in scope when it executes code, stores company data, or requires a company
identity. Password or MFA recovery for an already approved application follows
MD-IT-003 or MD-IT-004 when the application delegates to the Meridian identity.
Hardware purchases follow MD-IT-005. A suspected malicious application,
unexpected consent screen, or exposed application credential is a security
incident under MD-IT-008. Personal purchases and reimbursement requests do not
create approval for company use.

## 3. Definitions

A **license seat** is one assignable right to use paid software. A **catalog
application** has completed security and procurement review and has a known
owner. A **new SaaS request** asks Meridian Dynamics to approve a service not
currently in the catalog. Employees may phrase these requests as “need access,”
“add a seat,” “trial expires,” “subscription renewal,” or “install this tool.”
**Least privilege** means assigning only the role required for current work. A
**license transfer** reassigns an unused seat rather than buying another.
**Restricted data** includes customer confidential data, security records, and
regulated personal data. **Shadow IT** is company work performed in software
that has not completed the required review.

## 4. Policy / Procedure

1. The requester provides the application name, business purpose, requested
   role, manager, cost center, required date, expected duration, and data types
   the application will store or process.
2. Business Applications checks the catalog and license inventory. An available
   seat for a catalog application may be assigned after manager approval. The
   team uses a transfer before purchasing a duplicate seat when the prior user
   no longer needs access.
3. A paid purchase or renewal requires manager and budget-owner approval. An
   administrator, finance role, or permission beyond the catalog baseline also
   requires the application owner’s approval.
4. A new SaaS service requires security and data-handling review before trial
   data or company credentials are entered. Restricted data may not be uploaded
   during an unapproved trial. Business Applications records the service owner,
   renewal date, and offboarding method.
5. After approval, Business Applications assigns the minimum role, confirms
   sign-in, and records the seat. Denied or deferred requests include a reason
   and, when available, an approved catalog alternative.

## 5. Priority & escalation

Business Applications owns `software_licensing` tickets. A planned catalog seat,
renewal, or role request is low urgency, P4, with a one-business-day initial
response; an employee’s use of the word “urgent” does not override the impact
matrix. An expired license that blocks one employee from a time-critical
customer deliverable is high urgency, P2, after the manager confirms the
deadline. A malfunction affecting multiple existing users may be an
`email_collaboration` or application outage rather than a license request and is
routed by impact under MD-IT-002. A suspicious consent prompt, unapproved
service containing company data, or exposed vendor credential is immediately
routed to IT Security as `security_incident`. Business Applications may not skip
security, procurement, or budget approval to meet a preferred date.

## 6. Related documents

MD-IT-002 defines P1–P4 when an existing business application outage is confused
with a license request. MD-IT-003 and MD-IT-004 govern central password and MFA
recovery. MD-IT-008 governs malicious software, risky consent, exposed
credentials, and unapproved data disclosure. MD-IT-009 requires license removal
and seat recovery during offboarding. MD-IT-010 limits software and data storage
on remote and personal devices.

## 7. Revision history

Version 1.0 became effective on 2026-07-01. It establishes the catalog-first
workflow, license-transfer preference, required request fields, restricted-data
ban during unapproved trials, and explicit approvals for cost, elevated roles,
security, and data handling.

