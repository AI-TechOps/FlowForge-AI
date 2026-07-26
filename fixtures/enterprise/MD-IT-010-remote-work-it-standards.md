---
doc_id: MD-IT-010
title: Remote Work IT Standards
version: "1.0"
effective_date: 2026-07-01
owner_team: IT Infrastructure
applies_to: Meridian Dynamics employees and contractors working outside company offices
review_cadence: Annual
---

# MD-IT-010 — Remote Work IT Standards

## 1. Purpose

This standard defines the minimum technology and security practices for working
outside a Meridian Dynamics office. It covers managed devices, home and public
networks, company data, physical privacy, and the boundary between a local
remote-work problem and the MeridianConnect VPN service. It addresses tickets
such as “home Wi-Fi is slow,” “can I use my personal laptop,” “hotel network
blocks VPN,” and “I cannot print company data at home.” The standard enables
remote work without treating an employee’s household network or personal
equipment as company-managed infrastructure.

## 2. Scope

The standard applies whenever employees or contractors access Meridian systems
from a home, hotel, customer site, shared workspace, or other non-office
location. Company work must use a managed, encrypted device unless a documented
exception is approved by IT Security. The standard covers local connectivity,
router hygiene, screen privacy, storage, printing, and device transport.
MeridianConnect installation, authentication, and VPN tunnel troubleshooting
are governed by MD-IT-001. Company laptop repair follows MD-IT-005. MFA device
recovery follows MD-IT-004. Meridian Dynamics does not administer an employee’s
internet provider, personal router, personal computer, smart-home equipment, or
household device.

## 3. Definitions

A **managed device** is company-enrolled, encrypted, patched, and remotely
supportable. A **trusted remote network** uses current encryption and a password
not shared publicly. An **untrusted network** includes open Wi-Fi, captive
portals, and networks controlled by an unknown party. Employees often say “home
internet,” “hotel Wi-Fi,” “coffee shop network,” “personal laptop,” or “remote
setup.” **Local connectivity** means the device cannot reliably reach ordinary
internet sites before the VPN connects. A **privacy zone** is a workspace where
screens and conversations cannot be casually observed. **Local storage** means
files saved outside approved synchronized company locations. A **remote-work
exception** is a time-limited, documented approval from IT Security, not verbal
permission from a manager.

## 4. Policy / Procedure

1. Use a managed device with disk encryption, automatic screen lock, current
   updates, and an approved authenticator. Do not disable security controls to
   improve performance or install unapproved remote-access software.
2. At home, use a password-protected network with current router firmware and a
   unique administrator password. Meridian support may help distinguish local
   connectivity from company-service failure but does not log in to personal
   routers or contact the employee’s provider.
3. On an open or hotel network, complete the legitimate captive portal before
   starting MeridianConnect. Avoid confidential work if the network behaves
   unexpectedly. Use an approved hotspot when available.
4. Store company files only in approved synchronized locations. Do not copy them
   to a personal device, personal cloud account, removable drive, or household
   printer. Prevent family members and other third parties from using the
   managed device.
5. Report a lost device, suspected observation of confidential data, unexpected
   certificate warning, or unknown remote-control prompt immediately under
   MD-IT-008. Preserve the exact warning and location; do not bypass it.

## 5. Priority & escalation

IT Infrastructure owns `network_access` when a managed device cannot establish
reliable remote connectivity or MeridianConnect access. A home-network question
or planned remote setup is low urgency, P4, with a one-business-day response. A
single employee with intermittent access and an alternate connection is medium
urgency, P3. A single employee blocked before a confirmed time-critical event is
high urgency, P2, but support remains limited to the managed device and company
services. Ten or more remote employees unable to reach Meridian services is
critical urgency and P1 under MD-IT-002. A personal internet-provider outage
remains outside company ownership and may be routed to Service Desk for general
guidance. Suspicious certificates, device loss, or possible observation of
confidential data is `security_incident` and immediately owned by IT Security.

## 6. Related documents

MD-IT-001 governs MeridianConnect VPN access, tunnel errors, and supported
authentication. MD-IT-002 defines impact and urgency for multi-user remote
outages. MD-IT-004 governs authenticator enrollment and lost-phone recovery.
MD-IT-005 governs managed laptops and approved peripherals. MD-IT-006 prohibits
unapproved software and SaaS used from remote locations. MD-IT-008 governs lost
devices, suspicious warnings, and data exposure.

## 7. Revision history

Version 1.0 became effective on 2026-07-01. It establishes the managed-device
requirement, boundaries for personal networks, approved storage and printing
rules, public-network safeguards, and explicit routing between remote
connectivity and security incidents.

