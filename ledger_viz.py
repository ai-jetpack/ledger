#!/usr/bin/env python3
"""Visualize the design ledger through ledger_api (read-only, except comments typed on the component map's issues).

  python ledger_viz.py serve [--port 8765]   live viewer at http://127.0.0.1:8765
  python ledger_viz.py html  [--out FILE]    self-contained snapshot (ledger.html)
"""
import argparse
import json
import os
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import ledger_api as A

TEMPLATE = os.path.join(A.HERE, "viewer.html")


def with_ro(db, fn):
    con = A.connect(db, readonly=True)
    try:
        return fn(con)
    finally:
        con.close()


def render(data):
    with open(TEMPLATE, encoding="utf-8") as f:
        return f.read().replace("/*__DATA__*/null", json.dumps(data).replace("</", "<\\/"))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=A.DEFAULT_DB)
    sp = p.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("serve"); s.add_argument("--port", type=int, default=8765); s.add_argument("--no-browser", action="store_true")
    s = sp.add_parser("html"); s.add_argument("--out", default=os.path.join(A.HERE, "ledger.html"))
    a = p.parse_args()

    if a.cmd == "html":
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(render(with_ro(a.db, A.snapshot)))
        print(f"wrote {a.out}")
        return

    class H(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, code, ctype, body):
            b = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_POST(self):
            # the one write: a comment typed by the user on a side-bar issue of the component map (author "user")
            try:
                if self.path.startswith("/api/comment"):
                    n = int(self.headers.get("Content-Length") or 0)
                    req = json.loads(self.rfile.read(min(n, 65536)).decode("utf-8"))
                    con = A.connect(a.db)
                    try:
                        cid = A.comment(con, "user", req["id"], str(req["text"]))
                    finally:
                        con.close()
                    self.send(200, "application/json", json.dumps({"comment": cid}))
                else:
                    self.send(404, "text/plain", "not found")
            except (A.LedgerError, KeyError, ValueError) as e:
                self.send(400, "text/plain", f"{type(e).__name__}: {e}")
            except Exception as e:
                self.send(500, "text/plain", f"{type(e).__name__}: {e}")

        def do_GET(self):
            try:
                if self.path.startswith("/api/version"):
                    self.send(200, "application/json", json.dumps({"version": with_ro(a.db, A.version)}))
                elif self.path.startswith("/api/ledger"):
                    self.send(200, "application/json", json.dumps(with_ro(a.db, A.snapshot)))
                elif self.path.startswith("/api/map"):
                    self.send(200, "application/json", json.dumps(with_ro(a.db, A.map_model)))
                elif self.path in ("/", "/index.html"):
                    with open(TEMPLATE, encoding="utf-8") as f:
                        self.send(200, "text/html; charset=utf-8", f.read())
                elif self.path.startswith("/components"):
                    with open(os.path.join(A.HERE, "components.html"), encoding="utf-8") as f:
                        self.send(200, "text/html; charset=utf-8", f.read())
                else:
                    self.send(404, "text/plain", "not found")
            except Exception as e:
                self.send(500, "text/plain", f"{type(e).__name__}: {e}")

    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    url = f"http://127.0.0.1:{a.port}/"
    print(f"ledger viewer at {url}  (Ctrl+C to stop)")
    if not a.no_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
