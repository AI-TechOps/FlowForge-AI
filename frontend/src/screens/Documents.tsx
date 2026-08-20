/**
 * Knowledge documents + upload (spec 07 screens 3 and 4). Administrator only.
 *
 * Ingestion is a background job, so the list is the status board for it. The
 * poll is conditional — it runs only while something is `pending` or
 * `processing` and stops dead once the corpus is ready, because a settled
 * corpus polled every three seconds is pure noise against the API for as long
 * as the tab is open.
 *
 * A failed document keeps its `error_message` and offers reingest. That is the
 * whole reason ingestion status is a first-class column: "why is my policy not
 * being cited?" is answered here, not by reading worker logs.
 */

import { useState } from "react";

import { useDocuments, useReingest, useUploadDocument } from "../api/hooks";
import {
  DocBadge,
  Empty,
  ErrorState,
  Icon,
  Loading,
  Modal,
  PageHead,
  Panel,
  timeAgo,
} from "../components/ui";
import { useToast } from "../components/Toast";
import { useTitle } from "../shell/Shell";
import { TID, testid } from "../testids";

const ACCEPT = ".pdf,.md,.txt";
const MAX_BYTES = 20 * 1024 * 1024;

export function Documents() {
  useTitle("Knowledge");
  const documents = useDocuments();
  const reingest = useReingest();
  const [uploading, setUploading] = useState(false);

  const busy = documents.data?.some((d) => d.status === "pending" || d.status === "processing");
  const totalChunks = documents.data?.reduce((sum, d) => sum + (d.chunk_count ?? 0), 0) ?? 0;

  return (
    <div {...testid(TID.documents)}>
      <PageHead
        eyebrow="Act 0 · the knowledge the agent may cite"
        title="Knowledge documents"
        subtitle="The corpus every recommendation must cite. A document that is not ready cannot ground an answer."
        actions={
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => setUploading(true)}
            {...testid(TID.uploadOpen)}
          >
            {Icon.upload({ size: 14 })}
            Upload
          </button>
        }
      />

      <Panel
        flush
        title={
          <>
            <span>Corpus</span>
            {documents.data && (
              <span className="faint" style={{ fontSize: "var(--fs-xs)", fontWeight: 400 }}>
                {documents.data.length} documents · {totalChunks} chunks
              </span>
            )}
            {busy && (
              <span className="badge badge--info">
                <span className="badge__dot badge__dot--live" />
                ingesting
              </span>
            )}
          </>
        }
      >
        {documents.isPending && <Loading label="Loading documents" />}
        {documents.isError && (
          <ErrorState error={documents.error} onRetry={() => void documents.refetch()} />
        )}
        {documents.data?.length === 0 && (
          <Empty
            title="No documents yet"
            body="Upload an IT policy and the agent can start citing it. Until then every run fails as ungrounded — which is the grounding rule working, not a bug."
            action={
              <button type="button" className="btn btn--primary" onClick={() => setUploading(true)}>
                Upload a document
              </button>
            }
          />
        )}

        {documents.data && documents.data.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Version</th>
                  <th>Status</th>
                  <th className="num">Chunks</th>
                  <th>Uploaded</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {documents.data.map((doc) => (
                  <tr key={doc.id} {...testid(TID.documentRow(doc.id))}>
                    <td className="wrap">
                      {doc.title}
                      {doc.status === "failed" && doc.error_message && (
                        <div
                          className="mono"
                          style={{ color: "var(--err)", fontSize: "var(--fs-xs)", marginTop: 2 }}
                        >
                          {doc.error_message}
                        </div>
                      )}
                    </td>
                    <td className="muted mono">{doc.version ?? "—"}</td>
                    <td>
                      <DocBadge status={doc.status} {...testid(TID.documentStatus(doc.id))} />
                    </td>
                    <td className="num muted">{doc.chunk_count ?? "—"}</td>
                    <td className="muted">{timeAgo(doc.created_at)}</td>
                    <td style={{ textAlign: "right" }}>
                      <button
                        type="button"
                        className="btn btn--sm"
                        disabled={reingest.isPending || doc.status === "processing"}
                        onClick={() => reingest.mutate(doc.id)}
                        {...testid(TID.documentReingest(doc.id))}
                        title="Re-extract, re-chunk and re-embed this document"
                      >
                        Reingest
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {uploading && <UploadModal onClose={() => setUploading(false)} />}
    </div>
  );
}

function UploadModal({ onClose }: { onClose: () => void }) {
  const upload = useUploadDocument();
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [version, setVersion] = useState("1");
  const [localError, setLocalError] = useState<string | null>(null);

  const pick = (chosen: File | null) => {
    setLocalError(null);
    if (!chosen) {
      setFile(null);
      return;
    }
    // Client-side validation is a courtesy that saves a round trip; the server
    // validates independently and is the one that decides.
    const ext = chosen.name.slice(chosen.name.lastIndexOf(".")).toLowerCase();
    if (![".pdf", ".md", ".txt"].includes(ext)) {
      setLocalError(`${ext || "That file type"} is not supported. Use PDF, Markdown or plain text.`);
      setFile(null);
      return;
    }
    if (chosen.size > MAX_BYTES) {
      setLocalError(
        `That file is ${(chosen.size / 1024 / 1024).toFixed(1)} MB. The limit is 20 MB.`,
      );
      setFile(null);
      return;
    }
    setFile(chosen);
    if (!title) setTitle(chosen.name.replace(/\.[^.]+$/, ""));
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!file) {
      setLocalError("Choose a file first.");
      return;
    }
    const form = new FormData();
    form.append("file", file);
    if (title.trim()) form.append("title", title.trim());
    form.append("version", version.trim() || "1");
    upload.mutate(form, {
      onSuccess: (doc) => {
        onClose();
        toast({
          tone: "ok",
          title: "Upload accepted",
          body: `${doc.title} is being extracted, chunked and embedded. The list shows live status.`,
        });
      },
    });
  };

  const error = localError ?? (upload.error instanceof Error ? upload.error.message : null);

  return (
    <Modal
      title="Upload document"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            form="upload-doc"
            className="btn btn--primary"
            disabled={upload.isPending || !file}
            {...testid(TID.uploadSubmit)}
          >
            {upload.isPending ? "Uploading…" : "Upload and ingest"}
          </button>
        </>
      }
    >
      <form id="upload-doc" onSubmit={submit} className="stack">
        <div className="field">
          <label className="field__label" htmlFor="u-file">
            File
          </label>
          <input
            id="u-file"
            className="input"
            type="file"
            accept={ACCEPT}
            style={{ height: "auto", padding: "var(--sp-2) var(--sp-3)" }}
            onChange={(e) => pick(e.target.files?.[0] ?? null)}
            {...testid(TID.uploadInput)}
          />
          <span className="field__hint">PDF, Markdown or plain text, up to 20 MB.</span>
        </div>

        <div className="form-grid">
          <div className="field">
            <label className="field__label" htmlFor="u-title">
              Title
            </label>
            <input
              id="u-title"
              className="input"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="VPN Access Policy"
            />
            <span className="field__hint">Shown in citations. Defaults to the filename.</span>
          </div>
          <div className="field">
            <label className="field__label" htmlFor="u-version">
              Version
            </label>
            <input
              id="u-version"
              className="input"
              value={version}
              onChange={(e) => setVersion(e.target.value)}
            />
          </div>
        </div>

        <div className="banner banner--info">
          Ingestion runs in the background — extract, chunk, embed, store. The list shows live
          status and this dialog closes as soon as the upload is accepted.
        </div>

        {error && (
          <div className="banner banner--err" role="alert" {...testid(TID.uploadError)}>
            {error}
          </div>
        )}
      </form>
    </Modal>
  );
}
