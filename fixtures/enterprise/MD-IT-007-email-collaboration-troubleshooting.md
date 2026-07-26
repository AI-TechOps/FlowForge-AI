---
doc_id: MD-IT-007
title: Email & Collaboration Troubleshooting Guide
version: "1.0"
effective_date: 2026-07-01
owner_team: Business Applications
applies_to: Meridian Mail, TeamSpace messaging, calendars, and approved conferencing
review_cadence: Semiannual
---

# MD-IT-007 — Email & Collaboration Troubleshooting Guide

## 1. Purpose

This guide provides safe first steps and routing for Meridian Mail, TeamSpace
chat, calendars, shared mailboxes, meeting invitations, and approved video
conferencing. It addresses employee language such as “email is not syncing,”
“messages stuck in outbox,” “calendar invite disappeared,” “chat will not load,”
and “camera does not work in a meeting.” The guide separates a local client
problem from a service-wide outage, a license request, network failure, or
phishing report. Business Applications owns the collaboration services, while
Service Desk gathers evidence and performs low-risk checks.

## 2. Scope

This guide applies to approved collaboration applications used with a Meridian
identity on managed computers, managed mobile profiles, and supported browsers.
It covers message delivery, synchronization, calendars, presence, shared
mailboxes, meetings, microphones, cameras, and screen sharing. It does not cover
buying a new application or license, which follows MD-IT-006. A total loss of
internet or VPN access follows MD-IT-001 or MD-IT-010. Physical failure of a
camera, headset, or room system follows MD-IT-005. Suspicious messages, links,
attachments, unexpected login pages, or unauthorized forwarding rules follow
MD-IT-008 and must not be troubleshot by opening the content.

## 3. Definitions

**Meridian Mail** is the approved email and calendar service. **TeamSpace** is
the approved chat and collaboration service. A **client issue** affects one
browser, application, device, or user while the service remains reachable
elsewhere. A **service incident** affects multiple users or prevents normal use
across devices. A **shared mailbox** is a team-owned address with delegated
access. Employees may report “not receiving email,” “outbox stuck,” “invite
missing,” “chat offline,” “meeting has no audio,” or “screen share blocked.”
**Message trace** is server-side delivery evidence gathered by Business
Applications. **Local cache** is synchronized data on a device; clearing it can
remove unsent work, so employees must not delete a profile unless instructed.

## 4. Policy / Procedure

1. The requester records the affected service, exact error, time first observed,
   device, network location, number of affected users, and whether the web
   version works. They do not attach confidential message contents unless
   specifically required through an approved channel.
2. Service Desk checks the service-status notice and asks the employee to try a
   supported browser or web client. If the web client works, the analyst checks
   client updates, available storage, and a normal restart. They do not delete a
   profile or cached outbox without preserving unsent work.
3. For a missing message, record sender, recipient, approximate timestamp, and
   subject without forwarding sensitive content. Business Applications performs
   message trace and checks quarantine or delivery rules.
4. For meetings, test the approved device controls and application permissions.
   A physically failed peripheral is routed to Workplace IT under MD-IT-005.
5. A suspicious message, unexpected forwarding rule, or credential prompt is
   immediately routed to IT Security under MD-IT-008. Do not click, reply,
   forward externally, or open an attachment for diagnosis.

## 5. Priority & escalation

Business Applications owns `email_collaboration` incidents. One employee with a
workaround, such as a functioning web client, is medium urgency, P3, with a
four-business-hour initial response. One employee unable to join a confirmed
time-critical customer meeting is high urgency, P2, with a thirty-minute
response. A service failure affecting 10 or more users, an executive broadcast,
or a critical operational mailbox with no alternate is critical urgency and P1
under MD-IT-002. A suspected phishing message remains `security_incident` even
when it arrived by email and is owned by IT Security, not Business Applications.
A physical headset or room-camera defect is `hardware` and owned by Workplace
IT. Service Desk is the fallback when the report is too vague to identify a
service or impact.

## 6. Related documents

MD-IT-002 defines escalation for multi-user service outages and time-critical
meetings. MD-IT-005 governs failed cameras, headsets, and room hardware.
MD-IT-006 governs license seats, subscriptions, and application roles.
MD-IT-008 governs phishing, malicious attachments, suspicious forwarding rules,
and credential prompts. MD-IT-001 and MD-IT-010 govern connectivity when every
collaboration service is unreachable from a remote network.

## 7. Revision history

Version 1.0 became effective on 2026-07-01. It adds the web-client comparison,
safe message-trace evidence fields, preservation of unsent work, explicit
phishing stop conditions, and routing boundaries among Business Applications,
IT Security, Workplace IT, and IT Infrastructure.

