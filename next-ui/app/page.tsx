"use client";

import { useEffect, useMemo, useState } from "react";

type Interaction = {
  message_id: string;
  subject: string;
  sender: string;
  sent_at: string;
  classification: string | null;
  draft_reply: string | null;
  error: string | null;
  processed_at: string | null;
  reply_sent_at: string | null;
};

type ActionState = {
  label: string;
  detail?: string;
};

const API_BASE = process.env.NEXT_PUBLIC_FORGEFLOW_API_BASE || "http://127.0.0.1:8000";

export default function DashboardPage() {
  const [rows, setRows] = useState<Interaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [action, setAction] = useState<ActionState | null>(null);
  const [error, setError] = useState<string | null>(null);

  const stats = useMemo(() => {
    return {
      total: rows.length,
      pending: rows.filter((row) => !row.classification && !row.error).length,
      drafts: rows.filter((row) => row.draft_reply && !row.reply_sent_at).length,
      sent: rows.filter((row) => row.reply_sent_at).length
    };
  }, [rows]);

  async function api<T>(path: string, options?: RequestInit): Promise<T> {
    const response = await fetch(`${API_BASE}${path}`, options);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || `Request failed: ${response.status}`);
    }
    return payload as T;
  }

  async function refresh() {
    const data = await api<Interaction[]>("/api/interactions");
    setRows(data);
  }

  async function runAction(label: string, fn: () => Promise<void>) {
    setError(null);
    setAction({ label });
    try {
      await fn();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setAction(null);
      setLoading(false);
    }
  }

  useEffect(() => {
    runAction("Loading interactions", async () => refresh());
  }, []);

  return (
    <main>
      <header className="topbar">
        <div>
          <h1>ForgeFlow</h1>
          <p>Outlook agent processing dashboard</p>
        </div>
        <div className="actions">
          <button disabled={Boolean(action)} onClick={() => runAction("Syncing Outlook", async () => {
            const result = await api<{ ingested: number }>("/api/sync-outlook", { method: "POST" });
            setAction({ label: "Syncing Outlook", detail: `${result.ingested} new emails` });
          })}>
            Sync Outlook
          </button>
          <button disabled={Boolean(action)} onClick={() => runAction("Processing emails", async () => {
            const result = await api<{ processed: number }>("/api/process", { method: "POST" });
            setAction({ label: "Processing emails", detail: `${result.processed} processed` });
          })}>
            Process
          </button>
        </div>
      </header>

      {(action || loading) && (
        <section className="progressPanel" aria-live="polite">
          <div className="progressCopy">
            <strong>{action?.label || "Loading"}</strong>
            <span>{action?.detail || "Waiting for the backend to finish..."}</span>
          </div>
          <div className="progressTrack">
            <div className="progressBar" />
          </div>
        </section>
      )}

      {error && <section className="errorPanel">{error}</section>}

      <section className="stats">
        <div><span>{stats.total}</span>Total</div>
        <div><span>{stats.pending}</span>Pending</div>
        <div><span>{stats.drafts}</span>Drafts</div>
        <div><span>{stats.sent}</span>Sent</div>
      </section>

      <section className="tableWrap">
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>From</th>
              <th>Subject</th>
              <th>Class</th>
              <th>Draft / Action</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.message_id}>
                <td>{formatDate(row.sent_at)}</td>
                <td>{row.sender}</td>
                <td>{row.subject}</td>
                <td><span className="pill">{row.classification || "pending"}</span></td>
                <td>
                  {row.error && <pre className="rowError">{row.error}</pre>}
                  {!row.error && row.draft_reply && (
                    <>
                      <pre>{row.draft_reply}</pre>
                      {row.reply_sent_at ? (
                        <div className="sent">Sent {formatDate(row.reply_sent_at)}</div>
                      ) : (
                        <button
                          disabled={Boolean(action)}
                          onClick={() => runAction("Sending reply", async () => {
                            await api("/api/send-reply", {
                              method: "POST",
                              headers: { "Content-Type": "application/json" },
                              body: JSON.stringify({ message_id: row.message_id })
                            });
                          })}
                        >
                          Send Reply
                        </button>
                      )}
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </main>
  );
}

function formatDate(value: string | null) {
  if (!value) return "";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}
