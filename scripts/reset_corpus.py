"""Wipe and re-ingest the Meridian corpus for one org.

    python scripts/reset_corpus.py [--org-id UUID] [--base-url URL]

Why this exists: embeddings are only comparable to other embeddings from the
same model. Gate runs leave the demo org full of chunks embedded by the fake
provider, and querying those with real Ollama vectors compares two unrelated
spaces — retrieval returns noise and any accuracy number measures the mismatch
rather than the agent. Switching providers therefore means re-ingesting.

Deletes every document in the org (chunks cascade), then uploads the ten
`fixtures/enterprise/MD-IT-*` files through the public API so ingestion runs
exactly as it does in production.
"""

import argparse
import asyncio
import sys
import time
import urllib.request
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from app.db import async_session_factory, engine
from app.models import Document, Organization
from dev_token import auth_header
from sqlalchemy import delete, select

CORPUS_DIR = REPO_ROOT / "fixtures" / "enterprise"
TERMINAL = {"ready", "failed"}
DEFAULT_ADMIN_EMAIL = "admin@demo"

# Administrator identity used for the HTTP half of the reset. Set once from
# --admin-email; every request derives its token from this plus the target org.
_admin_email = DEFAULT_ADMIN_EMAIL


def _org_auth(base_url: str, org_id: uuid.UUID) -> dict[str, str]:
    """Authenticate as an administrator *in the org being reset*.

    The org id is part of the token request, not just of the database work.
    Previously every upload used the default demo identity regardless of
    --org-id, so pointing the script at another tenant deleted that tenant's
    corpus from Postgres and then re-ingested the replacement documents into
    the demo tenant — a destructive operation and a restore that disagreed
    about who they were for (Codex Phase 4 finding 8).
    """
    return auth_header(base_url, _admin_email, str(org_id))


async def _resolve_org(org_id: uuid.UUID | None) -> uuid.UUID:
    async with async_session_factory() as session:
        if org_id is not None:
            return org_id
        resolved = (
            await session.execute(
                select(Organization.id).order_by(Organization.created_at).limit(1)
            )
        ).scalar_one_or_none()
        if resolved is None:
            raise SystemExit("no organization found; run scripts/seed.py first")
        return resolved


async def _wipe(org_id: uuid.UUID) -> int:
    async with async_session_factory() as session:
        result = await session.execute(
            delete(Document).where(Document.org_id == org_id)
        )
        await session.commit()
        return result.rowcount or 0


def _upload(base_url: str, org_id: uuid.UUID, path: Path) -> str:
    boundary = "----flowforge-reset-corpus"
    title = path.stem.replace("-", " ")
    parts: list[bytes] = []
    for name, value in (("title", title), ("version", "1")):
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n".encode()
        )
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="{path.name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()
    )
    parts.append(path.read_bytes())
    parts.append(f"\r\n--{boundary}--\r\n".encode())

    request = urllib.request.Request(
        f"{base_url}/api/documents",
        data=b"".join(parts),
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            # Phase 4: the tenant is the token's, not the header's — so the
            # token has to be for the org we are resetting.
            **_org_auth(base_url, org_id),
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        import json

        return json.load(response)["id"]


def _await_ingestion(
    base_url: str, org_id: uuid.UUID, timeout: float = 900.0
) -> list[dict]:
    import json

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        request = urllib.request.Request(
            f"{base_url}/api/documents", headers=_org_auth(base_url, org_id)
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            documents = json.load(response)
        if documents and all(d["status"] in TERMINAL for d in documents):
            return documents
        time.sleep(3)
    raise SystemExit("ingestion did not finish in time")


def _verify_admin_org(base_url: str, org_id: uuid.UUID) -> None:
    import json

    request = urllib.request.Request(
        f"{base_url}/api/me", headers=_org_auth(base_url, org_id)
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        identity = json.load(response)
    if str(identity.get("org_id")) != str(org_id):
        raise SystemExit(
            f"{_admin_email} authenticates into org {identity.get('org_id')}, "
            f"not {org_id}; refusing to wipe a corpus this token cannot restore"
        )


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org-id", type=uuid.UUID, default=None)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument(
        "--admin-email",
        default=DEFAULT_ADMIN_EMAIL,
        help="Administrator to act as. Must belong to --org-id.",
    )
    arguments = parser.parse_args()

    global _admin_email
    _admin_email = arguments.admin_email

    org_id = await _resolve_org(arguments.org_id)
    # Prove the identity matches the target BEFORE deleting anything. A wipe
    # that succeeds followed by uploads into a different tenant is the worst
    # possible ordering: the corpus is gone and the restore went elsewhere.
    _verify_admin_org(arguments.base_url, org_id)

    removed = await _wipe(org_id)
    print(f"org {org_id}: deleted {removed} document(s)")

    sources = sorted(
        p for p in CORPUS_DIR.glob("MD-IT-*") if p.suffix in {".pdf", ".md", ".txt"}
    )
    if not sources:
        raise SystemExit(f"no corpus files found under {CORPUS_DIR}")
    for path in sources:
        _upload(arguments.base_url, org_id, path)
        print(f"  uploaded {path.name}")

    documents = _await_ingestion(arguments.base_url, org_id)
    ready = [d for d in documents if d["status"] == "ready"]
    chunks = sum(d["chunk_count"] for d in documents)
    print(f"\n{len(ready)}/{len(documents)} ready, {chunks} chunks")
    for document in documents:
        if document["status"] != "ready":
            print(f"  FAILED {document['title']}: {document['error_message']}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
