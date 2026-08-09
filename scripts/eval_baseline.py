"""G2.4 eval smoke: triage the labeled seed set and score category accuracy.

    python scripts/eval_baseline.py [--base-url URL] [--org-id UUID] [--limit N]

Compares agent output against the answer key in `fixtures/eval_tickets.json`
(labels the agent never sees — the loader deliberately omits them).

The number this prints is only meaningful with a REAL model. Run it with
LLM_PROVIDER=ollama (or openai); the fake provider classifies by hash, not
meaning, so its accuracy is noise and must never be recorded as a baseline.
Formal evaluation lands in Phase 5 — this is the ≥70% smoke bar.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = REPO_ROOT / "fixtures" / "eval_tickets.json"
TERMINAL = {"completed", "failed"}


def _request(url: str, method: str = "GET", org_id: str | None = None) -> dict:
    request = urllib.request.Request(url, method=method)
    if org_id:
        request.add_header("X-Org-Id", org_id)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def _await_run(base_url: str, run_id: str, org_id: str | None, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = _request(f"{base_url}/api/runs/{run_id}", org_id=org_id)
        if run["status"] in TERMINAL:
            return run
        time.sleep(2)
    return {"status": "timeout", "output": None, "failure_reason": "harness_timeout"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--org-id", default=None)
    parser.add_argument("--limit", type=int, default=0, help="0 = all seed tickets")
    parser.add_argument("--run-timeout", type=float, default=300.0)
    arguments = parser.parse_args()

    labels = {
        record["id"]: record["labels"]
        for record in json.loads(FIXTURE.read_text(encoding="utf-8"))["eval_tickets"]
    }

    tickets = _request(
        f"{arguments.base_url}/api/tickets?is_eval_seed=true", org_id=arguments.org_id
    )
    if arguments.limit:
        tickets = tickets[: arguments.limit]
    if not tickets:
        print("no eval-seed tickets found; run scripts/load_eval_tickets.py first")
        return 2

    fields = ("category", "urgency", "recommended_team")
    correct = dict.fromkeys(fields, 0)
    scored = failed = 0
    rows = []

    for ticket in tickets:
        expected = labels.get(ticket["external_ref"])
        if expected is None:
            continue
        started = _request(
            f"{arguments.base_url}/api/tickets/{ticket['id']}/triage",
            method="POST",
            org_id=arguments.org_id,
        )
        run = _await_run(
            arguments.base_url, started["id"], arguments.org_id, arguments.run_timeout
        )
        output = run.get("output") or {}

        if run["status"] != "completed":
            failed += 1
            rows.append(
                (ticket["external_ref"], run.get("failure_reason") or run["status"], "")
            )
            continue

        scored += 1
        marks = []
        for field in fields:
            hit = output.get(field) == expected.get(field)
            correct[field] += int(hit)
            marks.append(f"{field[:3]}{'✓' if hit else '✗'}")
        rows.append(
            (ticket["external_ref"], output.get("category", "?"), " ".join(marks))
        )

    total = scored + failed
    print(f"\n{'ticket':<10} {'result':<22} marks")
    for ref, result, marks in rows:
        print(f"{ref:<10} {result!s:<22} {marks}")

    print(f"\nruns: {total}  completed: {scored}  failed: {failed}")
    if scored:
        for field in fields:
            pct = 100.0 * correct[field] / scored
            print(f"  {field:<18} {correct[field]:>2}/{scored}  {pct:5.1f}%")
        category_accuracy = 100.0 * correct["category"] / scored
        print(
            f"\nG2.4 bar: category accuracy >= 70%  ->  {'PASS' if category_accuracy >= 70 else 'FAIL'}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
