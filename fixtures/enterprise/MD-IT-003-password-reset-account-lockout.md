---
doc_id: MD-IT-003
title: Password Reset & Account Lockout Procedure
version: "1.0"
effective_date: 2026-07-01
owner_team: IT Security
applies_to: Meridian Dynamics employees and contractors with a Meridian identity
review_cadence: Annual
---

# MD-IT-003 — Password Reset & Account Lockout Procedure

## 1. Purpose

This procedure restores access to a Meridian Dynamics identity when an employee
has forgotten a password, sees “account locked,” or cannot sign in after several
failed attempts. It defines the approved self-service and assisted recovery
paths, the identity checks required before a reset, and the point at which a
routine access problem becomes a security incident. A password reset changes a
credential; it does not repair MFA enrollment, VPN connectivity, application
licensing, or a service outage. The intended result is fast recovery without
allowing a caller, chat participant, or email sender to take over another
person’s account. Employees must never send an existing password, recovery code,
or one-time code to support staff.

## 2. Scope

This procedure applies to the primary Meridian identity used for company email,
MeridianConnect VPN, approved business applications, and managed workstations.
It covers forgotten passwords, expired passwords, and automatic lockout after
five failed sign-in attempts within fifteen minutes. It also covers an employee
who says “my password suddenly stopped working” when no broader outage is
reported. MFA device loss and authenticator recovery are governed by MD-IT-004.
An application-specific password owned by a vendor is routed to Business
Applications. A report that another person may know the password, that an
unexpected reset notice arrived, or that unfamiliar sign-ins appear is excluded
from routine reset handling and must be treated as a security incident under
MD-IT-008.

## 3. Definitions

The **Meridian identity** is the employee’s central company account. An
**account lockout** is a temporary sign-in block caused by five failed attempts;
employees often describe it as “locked out of my account,” “too many attempts,”
or “login disabled.” **Self-service recovery** uses the approved identity portal
and a previously enrolled factor without Service Desk intervention. An
**assisted reset** is initiated by Service Desk only after identity verification.
**Identity verification** means matching the employee identifier and manager
relationship in the directory plus a live confirmation through an already
registered channel. Knowledge of department, job title, or recent tickets is not
sufficient. A **suspected account takeover** is any access problem accompanied
by unexpected prompts, unknown sign-ins, changed recovery details, or a report
that credentials were disclosed.

## 4. Policy / Procedure

1. The employee first opens the approved identity portal from a known company
   bookmark and selects “Forgot password” or “Unlock account.” They complete a
   challenge using a previously enrolled factor. A successful self-service
   unlock may take up to five minutes to propagate.
2. If self-service is unavailable, Service Desk records the employee identifier
   but never asks for a current password or one-time code. The analyst verifies
   the directory record and sends a confirmation through a registered device or
   manager-attested company channel. The manager may confirm employment but
   cannot receive or choose the employee’s temporary credential.
3. After verification, Service Desk issues a single-use temporary password that
   expires in thirty minutes. The employee signs in and chooses a unique
   password. Reusing any of the previous twelve passwords is prohibited.
4. If the account locks again after one verified reset, Service Desk stops
   repeated resets and checks for a stale saved credential on mobile mail, VPN,
   or another managed device.
5. If verification fails, recovery details changed unexpectedly, or compromise
   is suspected, no reset is completed. The analyst preserves the ticket and
   immediately routes it to IT Security under MD-IT-008.

## 5. Priority & escalation

IT Security owns access-control policy; Service Desk performs verified routine
resets. One employee who is locked out with no imminent business deadline is
`account_access`, medium urgency, and normally P3 with a four-business-hour
initial response. A new employee blocked on their first workday or a single
employee unable to join a time-critical customer event is high urgency and P2,
with a thirty-minute initial response. Ten or more employees unable to
authenticate indicates a possible identity-service outage: classify it as
critical, assign P1, and escalate immediately to IT Infrastructure and IT
Security under MD-IT-002. Unknown sign-ins, disclosed credentials, or an
unexpected password reset are `security_incident`, critical urgency when active
compromise is confirmed, and owned by IT Security. Service Desk must not lower a
security escalation merely because a password reset appears to restore access.

## 6. Related documents

MD-IT-004 governs MFA enrollment, lost authenticators, and recovery codes, which
may be required after the password has been restored. MD-IT-008 governs phishing,
credential disclosure, unexpected resets, and suspected account takeover.
MD-IT-002 defines the P1–P4 impact and urgency matrix used when the number of
affected employees or business timing changes the priority. MD-IT-009 includes
the manager and identity checks required during onboarding and offboarding.

## 7. Revision history

Version 1.0 became effective on 2026-07-01. It establishes the five-attempt
lockout threshold, the thirty-minute temporary credential lifetime, the
registered-channel verification rule, and explicit escalation from routine
account recovery to security-incident handling.

