import { when } from "../data";
import type { Message, Run } from "../types";

export function Thread({ messages }: { messages: Message[] }) {
  if (!messages.length) return null;
  return (
    <details>
      <summary>Source emails ({messages.length})</summary>
      {messages.map((m) => (
        <div className="msg" key={m.message_id}>
          <div className="msg-head">
            <strong>{m.sender || "unknown"}</strong> → {m.recipients || "—"} · {when(m.sent_at)}
          </div>
          <div className="msg-body">{m.body_text || ""}</div>
          {m.draft_reply && (
            <div className="reply">
              <div className="msg-head">↳ agent reply</div>
              <div className="msg-body">{m.draft_reply}</div>
            </div>
          )}
        </div>
      ))}
    </details>
  );
}

export function Runs({ runs }: { runs: Run[] }) {
  if (!runs.length) return null;
  return (
    <details>
      <summary>Agent runs ({runs.length})</summary>
      {runs.map((r) => (
        <div className="run" key={r.message_id + (r.processed_at ?? "")}>
          {when(r.processed_at)} · {r.sent_reply ? <span className="ok">replied</span> : "no reply"} ·{" "}
          {r.session_id ? (
            <a
              href={`https://platform.claude.com/workspaces/default/sessions/${r.session_id}`}
              target="_blank"
              rel="noopener"
            >
              {r.session_id}
            </a>
          ) : (
            "no session"
          )}
        </div>
      ))}
    </details>
  );
}
