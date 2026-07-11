#!/usr/bin/env bash
# Enable branch protection on main for AI-TechOps/FlowForge-AI.
#
# Requires the repo to be PUBLIC or the org to be on a paid GitHub plan
# (branch protection is not available for private repos on the free tier).
#
# Auth: uses `gh` if logged in, otherwise set GITHUB_TOKEN.
#   gh auth login    # or: export GITHUB_TOKEN=<token with repo admin>
set -euo pipefail

REPO="AI-TechOps/FlowForge-AI"

gh api -X PUT "repos/$REPO/branches/main/protection" --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["lint", "test", "secret-scan"]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": 2,
    "require_code_owner_reviews": true,
    "dismiss_stale_reviews": true
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
JSON

echo "Branch protection enabled on $REPO:main"
