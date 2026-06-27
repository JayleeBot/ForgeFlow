from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from forgeflow.graph import GraphMailbox
from forgeflow.processor import ingest_messages, process_pending
from forgeflow.store import connect, recent_interactions


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ForgeFlow Dashboard</title>
  <style>
    body { margin: 0; font: 14px/1.45 system-ui, -apple-system, Segoe UI, sans-serif; color: #1f2937; background: #f6f7f9; }
    header { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 18px 24px; background: #fff; border-bottom: 1px solid #d9dde3; }
    h1 { margin: 0; font-size: 20px; }
    button { border: 1px solid #9aa4b2; background: #fff; border-radius: 6px; padding: 8px 12px; cursor: pointer; }
    main { padding: 20px 24px; }
    table { width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #d9dde3; }
    th, td { padding: 10px; border-bottom: 1px solid #e5e7eb; text-align: left; vertical-align: top; }
    th { font-size: 12px; text-transform: uppercase; color: #4b5563; background: #f9fafb; }
    pre { white-space: pre-wrap; max-width: 520px; margin: 0; }
    .pill { display: inline-block; border-radius: 999px; padding: 2px 8px; background: #e5e7eb; }
    .error { color: #b42318; }
  </style>
</head>
<body>
  <header>
    <h1>ForgeFlow Email Processing</h1>
    <div>
      <button onclick="syncOutlook()">Sync Outlook</button>
      <button onclick="processPending()">Process</button>
    </div>
  </header>
  <main><table id="rows"></table></main>
  <script>
    async function api(path, options) {
      const res = await fetch(path, options);
      if (!res.ok) throw new Error(await res.text());
      return res.json();
    }
    async function refresh() {
      const data = await api('/api/interactions');
      document.querySelector('#rows').innerHTML = `
        <tr><th>Time</th><th>From</th><th>Subject</th><th>Class</th><th>Draft / Error</th></tr>
        ${data.map(row => `
          <tr>
            <td>${escapeHtml(row.sent_at || '')}</td>
            <td>${escapeHtml(row.sender || '')}</td>
            <td>${escapeHtml(row.subject || '')}</td>
            <td><span class="pill">${escapeHtml(row.classification || 'pending')}</span></td>
            <td>${row.error ? `<pre class="error">${escapeHtml(row.error)}</pre>` : `<pre>${escapeHtml(row.draft_reply || '')}</pre>`}</td>
          </tr>`).join('')}`;
    }
    async function syncOutlook() { await api('/api/sync-outlook', {method: 'POST'}); await refresh(); }
    async function processPending() { await api('/api/process', {method: 'POST'}); await refresh(); }
    function escapeHtml(s) {
      return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    }
    refresh();
  </script>
</body>
</html>"""


def run_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Dashboard: http://{host}:{port}")
    server.serve_forever()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if urlparse(self.path).path == "/api/interactions":
            with connect() as conn:
                self._json(recent_interactions(conn))
            return
        self._html(HTML)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/sync-outlook":
                self._json({"ingested": ingest_messages(GraphMailbox().fetch_recent())})
            elif path == "/api/process":
                self._json({"processed": process_pending()})
            else:
                self.send_error(404)
        except Exception as exc:
            self._json({"error": f"{type(exc).__name__}: {exc}"}, status=500)

    def log_message(self, format: str, *args) -> None:
        return

    def _json(self, payload, status: int = 200) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _html(self, payload: str) -> None:
        data = payload.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
