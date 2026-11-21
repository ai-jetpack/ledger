#!/usr/bin/env python3
"""MCP server (stdio) exposing the design ledger API to agents.

  python ledger_mcp.py --author alpha

The author is fixed per server instance, so an agent can only write as itself. No admin operations
(delete, comment/vote editing) are exposed. Results are compact text to keep agent contexts small.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ledger_api as A  # noqa: E402

PROTOCOL = "2025-06-18"
ID = {"type": "string", "description": "entry id, e.g. L-0042"}


def tool(name, desc, props=None, required=()):
    return {"name": name, "description": desc,
            "inputSchema": {"type": "object", "properties": props or {}, "required": list(required)}}


TOOLS = [
    tool("ledger_queue", "Entries you must (re)vote on: new, or changed since your vote. Your work list for reviews."),
    tool("ledger_get", "Full entries: body, votes, references, comments.",
         {"ids": {"type": "array", "items": ID}, "comments": {"type": "integer", "description": "last N comments (default 6, -1 = all)"}},
         ["ids"]),
    tool("ledger_find", "One line per active entry, filtered. Use before adding, to avoid duplicates.",
         {"query": {"type": "string", "description": "words that must all appear"}, "kind": {"type": "string"},
          "status": {"type": "string"}, "limit": {"type": "integer", "description": "default 40"},
          "author": {"type": "string", "description": "'user' = the user's authoritative decisions"}}),
    tool("ledger_disputes", "Entries whose voters disagree, with each vote and the comment id to reply to."),
    tool("ledger_similar", "Candidate duplicate pairs by word overlap.",
         {"threshold": {"type": "number", "description": "default 0.4"},
          "ids": {"type": "array", "items": ID, "description": "only pairs involving these"}}),
    tool("ledger_add", "Add an entry. kind: " + ", ".join(A.KINDS) + ". status: " + ", ".join(A.STATUSES) + ".",
         {"kind": {"type": "string"}, "title": {"type": "string"}, "body": {"type": "string"},
          "status": {"type": "string"},
          "refs": {"type": "array", "description": "at least one",
                   "items": {"type": "object", "properties": {"id": ID, "comment": {"type": "string", "description": "the relationship"}},
                             "required": ["id", "comment"]}}},
         ["kind", "title", "body", "refs"]),
    tool("ledger_update", "Edit one of YOUR entries (logged with the reason).",
         {"id": ID, "reason": {"type": "string"}, "title": {"type": "string"}, "body": {"type": "string"},
          "kind": {"type": "string"}, "status": {"type": "string"}}, ["id", "reason"]),
    tool("ledger_comment", "Comment on an entry; reply_to threads it under a comment.",
         {"id": ID, "text": {"type": "string"}, "reply_to": {"type": "integer"}}, ["id", "text"]),
    tool("ledger_vote", "Vote up/down with a specific reason (replaces your previous vote).",
         {"id": ID, "value": {"type": "string", "enum": ["up", "down"]}, "reason": {"type": "string"},
          "reply_to": {"type": "integer"}}, ["id", "value", "reason"]),
    tool("ledger_link", "Add or update a reference from -> to with its relationship.",
         {"from": ID, "to": ID, "comment": {"type": "string"}}, ["from", "to", "comment"]),
    tool("ledger_unlink", "Remove a reference.", {"from": ID, "to": ID, "reason": {"type": "string"}}, ["from", "to", "reason"]),
    tool("ledger_merge", "Merge duplicate 'from' into 'into'. Only when both agents agreed it is a duplicate.",
         {"from": ID, "into": ID, "reason": {"type": "string"}}, ["from", "into", "reason"]),
]


# ---------------------------------------------------------------- compact formatting
def fmt_line(d):
    return f"{d['id']} {d['score']:+d} [{d['kind']}/{d['status']}] {d['title']}"


def fmt_entry(d):
    out = [f"{d['id']} [{d['kind']}/{d['status']}] score {d['score']:+d} by {d['author']}", f"title: {d['title']}"]
    if "merged_into" in d:
        out.append(f"MERGED INTO {d['merged_into']}")
    if d["body"]:
        out.append(d["body"])
    out += [f"vote {v['voter']} {v['value']:+d}: {v['reason']}" for v in d["votes"]]
    out += [f"-> {r['id']} {r['title']}: {r['comment']}" for r in d["references"]]
    out += [f"<- {r['id']} {r['title']}: {r['comment']}" for r in d["referenced_by"]]
    hidden = d["comment_count"] - len(d["comments"])
    if hidden:
        out.append(f"({hidden} older comments not shown)")
    out += [f"#{c['id']} {c['author']}{' re #' + str(c['reply_to']) if c['reply_to'] else ''}: {c['text']}" for c in d["comments"]]
    return "\n".join(out)


def run(con, author, name, a):
    if name == "ledger_queue":
        q = A.review_queue(con, author)
        return "\n".join(fmt_line(d) for d in q) + f"\n({len(q)} to review)" if q else "nothing to review"
    if name == "ledger_get":
        n = a.get("comments", 6)
        return "\n\n".join(fmt_entry(d) for d in A.get(con, a["ids"], comments="all" if n < 0 else ("none" if n == 0 else n)))
    if name == "ledger_find":
        lim = a.get("limit", 40)
        rows = A.find(con, a.get("query"), a.get("kind"), a.get("status"), author=a.get("author"))
        more = f"\n({len(rows) - lim} more; narrow the query)" if len(rows) > lim else ""
        return ("\n".join(fmt_line(d) for d in rows[:lim]) + more) if rows else "no match"
    if name == "ledger_disputes":
        ds = A.disputes(con)
        return "\n".join(fmt_line(d) + "".join(f"\n  {v['voter']} {v['value']:+d} (reply to #{v['comment_id']}): {v['reason']}"
                                               for v in d["votes"]) for d in ds) or "no disputes"
    if name == "ledger_similar":
        ps = A.similar(con, a.get("threshold", 0.4), a.get("ids"))
        return "\n".join(f"{p['score']:.2f} {p['a']} {p['a_title']} <-> {p['b']} {p['b_title']}" for p in ps) or "no candidate pairs"
    if name == "ledger_add":
        if not a.get("refs"):
            raise A.LedgerError("at least one reference is required")
        return A.add(con, author, a["kind"], a["title"], a.get("body", ""), a.get("status", "proposed"),
                     [(r["id"], r["comment"]) for r in a["refs"]])
    if name == "ledger_update":
        row = A.get(con, [a["id"]], comments="all")[0]
        if row["author"] != author:
            raise A.LedgerError(f"{row['id']} belongs to {row['author']}; comment on it instead")
        if any(c["author"] in A.ADMINS and c["text"].startswith("[edit") for c in row["comments"]):
            raise A.LedgerError(f"{row['id']} records a user decision; comment on it instead of editing")
        return "updated " + A.update(con, author, a["id"], a["reason"], a.get("title"), a.get("body"), a.get("kind"), a.get("status"))
    if name == "ledger_comment":
        return f"comment #{A.comment(con, author, a['id'], a['text'], a.get('reply_to'))}"
    if name == "ledger_vote":
        r = A.vote(con, author, a["id"], a["value"], a["reason"], a.get("reply_to"))
        return f"{r['id']} score {r['score']:+d}"
    if name == "ledger_link":
        return A.link(con, author, a["from"], a["to"], a["comment"])
    if name == "ledger_unlink":
        return "removed" if A.unlink(con, author, a["from"], a["to"], a["reason"]) else "no such reference"
    if name == "ledger_merge":
        return A.merge(con, author, a["from"], a["into"], a["reason"])
    raise A.LedgerError(f"unknown tool {name}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--author", required=True)
    p.add_argument("--db", default=A.DEFAULT_DB)
    args = p.parse_args()
    if args.author in A.ADMINS:
        sys.exit("agents may not use an admin author")
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    con = A.connect(args.db)

    def reply(mid, result=None, error=None):
        msg = {"jsonrpc": "2.0", "id": mid}
        msg["error" if error else "result"] = error or result
        sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            reply(None, error={"code": -32700, "message": "parse error"})
            continue
        mid, method = req.get("id"), req.get("method")
        if mid is None:          # notification (e.g. notifications/initialized)
            continue
        if method == "initialize":
            reply(mid, {"protocolVersion": req.get("params", {}).get("protocolVersion", PROTOCOL),
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": f"ledger-{args.author}", "version": "1.0"}})
        elif method == "tools/list":
            reply(mid, {"tools": TOOLS})
        elif method == "tools/call":
            prm = req.get("params", {})
            try:
                text = run(con, args.author, prm.get("name"), prm.get("arguments") or {})
                reply(mid, {"content": [{"type": "text", "text": str(text)}]})
            except (A.LedgerError, KeyError, ValueError, TypeError) as e:
                reply(mid, {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True})
        elif method == "ping":
            reply(mid, {})
        else:
            reply(mid, error={"code": -32601, "message": f"method not found: {method}"})


if __name__ == "__main__":
    main()
