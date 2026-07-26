# Meridian Dynamics enterprise corpus

Review status: **draft pending FlowForge code-owner review**.

This directory contains the fictional Meridian Dynamics IT corpus defined by
spec 09. The 10 ingestion fixtures are:

- `MD-IT-001-vpn-access-policy.pdf`
- `MD-IT-002-incident-priority-escalation-guidelines.pdf`
- `MD-IT-003-password-reset-account-lockout.md`
- `MD-IT-004-mfa-enrollment-recovery.md`
- `MD-IT-005-hardware-request-replacement.md`
- `MD-IT-006-software-saas-license-request.md`
- `MD-IT-007-email-collaboration-troubleshooting.md`
- `MD-IT-008-security-incident-reporting-policy.pdf`
- `MD-IT-009-onboarding-offboarding-checklist.txt`
- `MD-IT-010-remote-work-it-standards.md`

`TEMPLATE.md` and `AUTHORING.md` define the onboarding pattern.
`taxonomy.json` is the closed label space. Reviewable Markdown sources for the
three generated PDFs live in `sources/`; regenerate or check them with:

```sh
python scripts/generate_enterprise_pdfs.py
python scripts/generate_enterprise_pdfs.py --check
```

Code owners must complete G9.1–G9.4 and G1.5 before treating any document,
taxonomy value, retrieval check, or eval-ticket label as approved.

