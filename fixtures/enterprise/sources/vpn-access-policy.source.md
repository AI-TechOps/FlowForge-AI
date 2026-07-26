---
doc_id: MD-IT-001
title: VPN Access Policy
version: "1.0"
effective_date: 2026-07-01
owner_team: IT Infrastructure
applies_to: Meridian Dynamics employees and contractors using remote network access
review_cadence: Annual
---

# MD-IT-001 - VPN Access Policy

## 1. Purpose

This policy governs remote access to Meridian Dynamics internal services through
the MeridianConnect VPN. It explains who may connect, which devices and
authentication methods are allowed, how to diagnose common reports such as “VPN
keeps disconnecting,” “VPN times out from home,” and “connected but cannot reach
the ERP,” and when to escalate. MeridianConnect protects company traffic over an
untrusted network; it does not repair an employee’s home internet service. The
intended result is reliable, auditable remote access without bypassing device,
identity, or network security controls.

## 2. Scope

The policy applies to active employees and approved contractors who use a
managed Meridian device outside a company office. Access is limited to services
authorized for the user’s role. Personal computers, rooted or jailbroken
devices, shared household devices, and unmanaged virtual machines may not
connect. A basic password or account lockout follows MD-IT-003, and a lost MFA
device follows MD-IT-004. A home internet outage or weak home Wi-Fi is outside
Meridian infrastructure ownership, although Service Desk may help identify that
boundary under MD-IT-010. Suspicious certificate warnings, unexpected approval
prompts, or evidence of credential theft are security incidents under MD-IT-008.

## 3. Definitions

**MeridianConnect** is the approved company VPN client and gateway. A **managed
device** is company-enrolled, encrypted, patched, and reporting healthy security
status. A **tunnel** is the protected network session created after sign-in and
MFA. Employees may describe tunnel trouble as “VPN drops,” “keeps
disconnecting,” “times out,” “stuck connecting,” or “connected but no access.”
A **local network problem** exists when ordinary internet sites are also slow or
unreachable before MeridianConnect starts. A **service outage** affects multiple
users or locations. A **certificate warning** says the remote identity cannot be
verified; users must not bypass it. **Split access** means public internet
traffic and approved company traffic follow their configured routes.

## 4. Policy / Procedure

1. Connect from a managed device with current updates, disk encryption, and an
   enrolled MFA method. Use only the installed MeridianConnect client and the
   published gateway; browser extensions and third-party VPN clients are not
   approved.
2. Before troubleshooting, confirm ordinary internet access without opening
   confidential services. On hotel or guest Wi-Fi, complete the legitimate
   captive portal before starting MeridianConnect. Never accept a certificate
   warning or disable endpoint protection.
3. If MeridianConnect times out or keeps disconnecting, record the timestamp,
   network type, client error, whether ordinary internet remained available,
   and whether another approved network works. Restart the client once. Do not
   repeatedly approve MFA prompts.
4. If the tunnel connects but one application is unavailable, record the
   application and error. IT Infrastructure checks routes and DNS; Business
   Applications handles an application outage or missing license.
5. Service Desk may collect approved client diagnostics. IT Infrastructure may
   reset a stale VPN session after verifying identity. Employees must not post
   logs containing addresses or identifiers in public channels.

## 5. Priority & escalation

IT Infrastructure owns `network_access` and MeridianConnect incidents. One
employee with intermittent VPN and a usable alternate network is medium urgency,
P3, with a four-business-hour initial response. One employee fully blocked
before a confirmed customer or operational deadline is high urgency, P2, with a
thirty-minute initial response. A MeridianConnect outage affecting 10 or more
users, two office locations, or a critical remote operation is critical urgency,
P1, with immediate response under MD-IT-002. A certificate warning, repeated
unexpected MFA prompts, or suspected credential disclosure changes the category
to `security_incident` and transfers ownership to IT Security immediately. A
personal internet-provider outage is routed to Service Desk for general guidance
and is not represented as a Meridian service failure.

## 6. Related documents

MD-IT-002 defines the impact and urgency matrix for P1–P4 assignment. MD-IT-003
governs password reset and lockout when the VPN credential is rejected.
MD-IT-004 governs MFA enrollment and lost-authenticator recovery. MD-IT-008
governs suspicious prompts, certificate warnings, and credential disclosure.
MD-IT-010 defines supported remote networks, managed-device standards, and the
boundary around personal internet service.

## 7. Revision history

Version 1.0 became effective on 2026-07-01. It establishes managed-device-only
access, approved diagnostics, the 10-user P1 threshold, clear ownership between
IT Infrastructure and Business Applications, and mandatory security escalation
for certificate or credential concerns.
