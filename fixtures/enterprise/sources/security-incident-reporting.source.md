---
doc_id: MD-IT-008
title: Security Incident Reporting Policy
version: "1.0"
effective_date: 2026-07-01
owner_team: IT Security
applies_to: Everyone with access to Meridian Dynamics devices, accounts, data, or facilities
review_cadence: Semiannual
---

# MD-IT-008 - Security Incident Reporting Policy

## 1. Purpose

This policy tells employees and contractors how to report suspected phishing,
credential disclosure, malware, lost devices, unauthorized access, data
exposure, and other security concerns. Early reporting is required even when the
reporter is uncertain or believes they made a mistake. Common tickets include
“I clicked a phishing link,” “I entered my password,” “unexpected MFA prompt,”
“laptop was stolen,” and “a file was shared with the wrong person.” The policy
prioritizes personal safety, containment, evidence preservation, and rapid IT
Security ownership. Reporting in good faith is encouraged and must not be
delayed while the employee investigates alone.

## 2. Scope

The policy applies to Meridian identities, managed and personal devices used for
company access, email and collaboration, business applications, physical media,
customer or company data, and suspicious activity observed at any location. It
covers suspected events; proof is not required before reporting. Routine spam
with no interaction may be reported through the approved message-report
control, while any click, attachment opening, credential entry, approval prompt,
or reply requires a support incident. Ordinary password lockout follows
MD-IT-003 only when no suspicious signal exists. Hardware failure follows
MD-IT-005 unless loss, theft, tampering, or safety is involved. Employees must
not contact a suspected attacker, affected external person, or law enforcement
on the company’s behalf unless directed.

## 3. Definitions

A **security incident** is suspected or confirmed activity that could harm
confidentiality, integrity, availability, identity, or physical device control.
**Phishing** is a deceptive message, call, or page intended to obtain
credentials, approval, money, or data. **Credential disclosure** occurs when a
password, recovery code, token, or MFA approval is provided to an untrusted
party. **Active compromise** means unauthorized access is observed or strongly
confirmed and may still be occurring. **Data exposure** means company or
customer information reached an unauthorized person or location. **Evidence
preservation** means keeping the message, timestamp, device state, address, and
error without altering or publicly sharing them. Employees may say “hacked,”
“clicked a bad link,” “sent to wrong person,” “virus pop-up,” or “phone stolen.”

## 4. Policy / Procedure

1. If there is physical danger, smoke, or threat, move to safety first and use
   local emergency procedures. Otherwise stop interacting with the suspicious
   message, page, device, or person.
2. Report immediately through the security incident channel or Service Desk.
   Include the time, device, account, what was clicked or entered, observed
   prompts, data involved, and current device location. State plainly if a
   password was entered or an MFA prompt approved.
3. Preserve evidence. Do not delete the message, wipe the device, forward the
   content externally, run unapproved cleanup tools, or continue testing a link.
   Disconnect a managed device from networks only when instructed or when
   obviously active malicious control is occurring; keep it powered on unless
   safety requires otherwise.
4. IT Security validates scope, contains sessions or devices, resets credentials
   through controlled procedures, and coordinates notifications. Service Desk
   does not independently promise that an incident is resolved.
5. Continue reporting new prompts or activity and follow the incident lead’s
   instructions. Business communications to customers or outside parties are
   made only by authorized Meridian Dynamics representatives.

## 5. Priority & escalation

IT Security owns every `security_incident`. Confirmed active compromise,
confirmed data exposure, dangerous device behavior, or unauthorized access to a
critical service is critical urgency and P1 with immediate paging. Suspected
phishing interaction, a clicked link, opened attachment, disclosed password,
unexpected MFA approval, stolen managed device, or suspected exposure without
confirmed access is high urgency and P2 with a fifteen-minute initial response.
An unclicked suspicious message reported through the approved control is medium
urgency, normally P3, unless a campaign affects 10 or more users, in which case
it escalates to P1 or P2 based on interaction and impact. General security
questions with no event are low urgency and may begin with Service Desk. The
reporter’s uncertainty never justifies downgrading observable risk; MD-IT-002
governs reassessment.

## 6. Related documents

MD-IT-002 defines the general impact and urgency matrix. MD-IT-003 governs
controlled password reset after IT Security contains a suspected account.
MD-IT-004 governs factor replacement after device loss or unexpected prompts.
MD-IT-005 governs safe handling and replacement after a device incident.
MD-IT-007 describes the boundary between collaboration troubleshooting and
phishing. MD-IT-009 covers urgent access revocation, and MD-IT-010 covers remote
privacy and suspicious network warnings.

## 7. Revision history

Version 1.0 became effective on 2026-07-01. It establishes immediate
good-faith reporting, explicit phishing and credential-disclosure examples,
evidence-preservation rules, fifteen-minute P2 response, confirmed-compromise P1
handling, and exclusive IT Security ownership of incident containment.
