---
doc_id: MD-IT-004
title: MFA Enrollment & Recovery
version: "1.0"
effective_date: 2026-07-01
owner_team: IT Security
applies_to: Meridian Dynamics workforce identities and approved authenticators
review_cadence: Annual
---

# MD-IT-004 — MFA Enrollment & Recovery

## 1. Purpose

This document defines how Meridian Dynamics employees enroll a multifactor
authentication method and recover when a phone is lost, replaced, wiped, or no
longer produces an accepted prompt. MFA protects a company identity with
something beyond a password. Recovery must therefore prove identity at least as
carefully as initial enrollment. The policy is written for tickets such as “new
phone, cannot approve MFA,” “authenticator codes do not work,” and “I lost my
phone and have no recovery code.” It gives employees a safe self-service path,
gives Service Desk a bounded assistance path, and reserves factor bypass and
security investigation for IT Security.

## 2. Scope

The policy applies to MFA used with the Meridian identity, MeridianConnect VPN,
company email, and business applications that delegate sign-in to the Meridian
identity service. Every active employee and contractor must maintain one primary
authenticator and one recovery method. A personal phone may be used only through
the approved authenticator and may not store company passwords in notes or
messages. Password problems without a functioning second factor follow
MD-IT-003. Vendor-specific MFA that does not use the Meridian identity is routed
to Business Applications. A stolen device, an MFA prompt the employee did not
initiate, repeated unexpected prompts, or a disclosed recovery code is a
security incident governed by MD-IT-008, not ordinary recovery.

## 3. Definitions

**MFA** requires a password plus an approved authenticator, security key, or
single-use recovery code. A **factor** is one enrolled proof of possession. A
**recovery code** is a one-time emergency code generated during enrollment; it
must be stored separately from the device and must never be pasted into a ticket.
Employees may say “push is not coming,” “six-digit code rejected,” “new phone,”
or “authenticator unavailable” when they need factor recovery. A **factor reset**
removes an unusable authenticator so a replacement can be enrolled. A
**temporary bypass** is a time-limited exception created only by IT Security
after verified business need; it is not a convenience workaround. **MFA
fatigue** means repeated unsolicited approval prompts intended to trick an
employee into accepting one.

## 4. Policy / Procedure

1. During initial enrollment, the employee signs in from a managed device,
   registers an approved authenticator, and confirms one test challenge. They
   then create recovery codes and store them in the approved secure vault,
   separate from the enrolled device.
2. Before replacing a working phone, the employee adds the new authenticator,
   completes a test challenge, and only then removes the old factor. This
   self-service transfer is the preferred path.
3. If the old phone is unavailable, the employee may use one unused recovery
   code at the identity portal. After successful sign-in, they enroll the new
   factor and regenerate the entire recovery-code set.
4. If neither an old factor nor a recovery code is available, Service Desk
   follows the registered-channel identity verification in MD-IT-003. Service
   Desk records the device-loss circumstances and sends the verified request to
   IT Security. Only IT Security may clear the last factor or issue a temporary
   bypass, which expires after four hours.
5. An employee who receives an unexpected prompt must deny it, stop attempting
   recovery, and report a security incident. Support staff never ask an employee
   to approve a prompt or reveal a code during a call or chat.

## 5. Priority & escalation

IT Security owns MFA enrollment and recovery; Service Desk performs initial
triage and identity verification. A planned phone replacement with the old
factor still available is `account_access`, low urgency, P4, with a
one-business-day initial response. A lost phone that blocks one employee but has
no suspicious prompts is `account_access`, high urgency, P2, with a thirty-minute
initial response after verification. An unexpected MFA prompt, repeated prompt
storm, stolen unlocked phone, or disclosed recovery code is
`security_incident`; IT Security responds within fifteen minutes and assigns P1
when active unauthorized access is confirmed, otherwise P2 while investigating.
If ten or more employees stop receiving MFA challenges, Service Desk declares a
critical identity-service incident and escalates to both IT Security and IT
Infrastructure under MD-IT-002.

## 6. Related documents

MD-IT-003 supplies the identity-verification requirements for assisted factor
recovery and explains password reset boundaries. MD-IT-008 supplies the
reporting and evidence-preservation steps for stolen devices, unexpected prompts,
or disclosed recovery codes. MD-IT-002 determines priority from impact and
urgency. MD-IT-010 defines security requirements for authenticators used during
remote work.

## 7. Revision history

Version 1.0 became effective on 2026-07-01. It establishes the two-method
enrollment expectation, safe phone-replacement sequence, four-hour maximum
temporary bypass, and mandatory IT Security escalation when no enrolled
recovery method remains.

