from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from forgeflow.graph import GraphMailbox
from forgeflow.processor import ingest_messages, process_pending
from forgeflow.store import connect, draft_reply_for_message, mark_reply_sent, recent_interactions
from forgeflow.store import rebuild_state_from_interactions, rfq_states


def run_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"API: http://{host}:{port}")
    server.serve_forever()


class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/interactions":
            with connect() as conn:
                self._json(recent_interactions(conn))
        elif path == "/api/rfqs":
            with connect() as conn:
                self._json(rfq_states(conn))
        elif path == "/api/health":
            self._json({"ok": True})
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/sync-outlook":
                self._json({"ingested": ingest_messages(GraphMailbox().fetch_recent())})
            elif path == "/api/process":
                self._json({"processed": process_pending()})
            elif path == "/api/rebuild-state":
                with connect() as conn:
                    self._json({"rebuilt": rebuild_state_from_interactions(conn)})
            elif path == "/api/send-reply":
                self._send_reply()
            else:
                self.send_error(404)
        except Exception as exc:
            self._json({"error": f"{type(exc).__name__}: {exc}"}, status=500)

    def log_message(self, format: str, *args) -> None:
        return

    def _send_reply(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        message_id = payload.get("message_id")
        if not message_id:
            self._json({"error": "message_id is required"}, status=400)
            return
        with connect() as conn:
            draft = draft_reply_for_message(conn, message_id)
            if not draft:
                self._json({"error": "No email found for message_id"}, status=404)
                return
            if not draft.get("draft_reply"):
                self._json({"error": "No draft reply for message_id"}, status=400)
                return
            if draft.get("reply_sent_at"):
                self._json({"sent": False, "reply_sent_at": draft["reply_sent_at"]})
                return
            GraphMailbox().reply(message_id, draft["draft_reply"])
            mark_reply_sent(conn, message_id)
        self._json({"sent": True})

    def _json(self, payload, status: int = 200) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
