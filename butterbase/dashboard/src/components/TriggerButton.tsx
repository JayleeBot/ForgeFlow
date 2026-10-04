import { useState } from "react";

const KEY_STORE = "forgeflow_trigger_key";

type Banner = { cls: "good" | "bad"; text: string } | null;

/**
 * fn/trigger runs one thread and can send mail, so it is gated by a key the
 * operator holds. The key lives in localStorage on this browser and is
 * deliberately NOT baked into the page, which is public.
 */
export default function TriggerButton({ url }: { url: string }) {
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState<Banner>(null);

  async function run() {
    let key = localStorage.getItem(KEY_STORE);
    if (!key) {
      key = prompt("Trigger key (FORGEFLOW_TRIGGER_KEY). Stored in this browser only.");
      if (!key) return;
      localStorage.setItem(KEY_STORE, key.trim());
    }

    setBusy(true);
    setBanner({ cls: "good", text: "Running one thread — a session takes up to a minute…" });
    try {
      // The key goes in a text/plain body, not a custom header: a custom header
      // would force a CORS preflight this API rejects, and the browser would
      // block the request before it left. text/plain is safelisted, so this is a
      // simple request with no preflight.
      const res = await fetch(url, {
        method: "POST",
        headers: { "content-type": "text/plain" },
        body: localStorage.getItem(KEY_STORE) ?? "",
      });
      const body = await res.json().catch(() => ({}) as Record<string, unknown>);

      if (res.status === 401) {
        localStorage.removeItem(KEY_STORE); // wrong key: make the next click re-prompt
        setBanner({ cls: "bad", text: "That trigger key was rejected. Click again to re-enter it." });
        return;
      }
      if (!res.ok) {
        const why = (body.error ?? body.message ?? "") as string;
        setBanner({ cls: "bad", text: `Trigger failed (HTTP ${res.status}). ${why}` });
        return;
      }
      if (!body.processed) {
        setBanner({
          cls: "good",
          text: `Nothing new to process — ${(body.reason as string) || "no unseen messages"}.`,
        });
        return;
      }

      const actions = (body.actions as string[] | undefined)?.join(", ") || "no action taken";
      setBanner({
        cls: "good",
        text:
          `Processed ${(body.subject as string) || (body.thread_id as string)} · ${actions} · ` +
          `${body.remaining} left. ${body.autosend ? "Replies were sent." : "Drafts only."} ` +
          "Redeploy to refresh this page.",
      });
    } catch (err) {
      setBanner({ cls: "bad", text: `Could not reach the trigger. ${(err as Error).message}` });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button className="primary" disabled={busy} onClick={run}>
        {busy ? "Processing…" : "Process new email"}
      </button>
      {banner && <div className={`banner ${banner.cls}`}>{banner.text}</div>}
    </>
  );
}
