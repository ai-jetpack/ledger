#!/usr/bin/env python3
"""Design ledger command line: a thin client of ledger_api (the only code that touches ledger.db).

Entry ids look like L-0001 ("L-1" or "1" also accepted). Text arguments accept @path to read from a file.
Run `python ledger.py -h` for commands.
"""
import argparse
import json
import os
import sys

import ledger_api as A


def text(v):
    if v is not None and v.startswith("@"):
        with open(v[1:], encoding="utf-8-sig") as f:
            return f.read()
    return v


def show_entry(d):
    print(f"{d['id']}  [{d['kind']}/{d['status']}]  score {d['score']:+d} (up {d['up']}, down {d['down']})")
    print(f"  title: {d['title']}")
    if "merged_into" in d:
        print(f"  MERGED INTO {d['merged_into']}")
    for line in (d.get("body") or "").splitlines():
        print(f"  | {line}")
    for v in d.get("votes", []):
        print(f"  vote {v['value']:+d} by {v['voter']}: {v['reason']}")
    for r in d.get("references", []):
        print(f"  -> {r['id']} ({r['title']}): {r['comment']}")
    for r in d.get("referenced_by", []):
        print(f"  <- {r['id']} ({r['title']}): {r['comment']}")
    for c in d.get("comments", []):
        rt = f" (reply to #{c['reply_to']})" if c["reply_to"] else ""
        print(f"  #{c['id']} {c['author']}{rt}: {c['text']}")


def line(d):
    m = f" -> merged into {d['merged_into']}" if "merged_into" in d else ""
    return f"{d['id']}  {d['score']:+d}  [{d['kind']}/{d['status']}]  {d['title']}{m}"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=A.DEFAULT_DB)
    p.add_argument("--json", action="store_true", help="print results as JSON")
    sp = p.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("add"); s.add_argument("--kind", required=True); s.add_argument("--title", required=True)
    s.add_argument("--body"); s.add_argument("--status", default="proposed"); s.add_argument("--author", required=True)
    s.add_argument("--ref", action="append", default=[], help="ID:relationship (repeatable)")
    s = sp.add_parser("update"); s.add_argument("id"); s.add_argument("--title"); s.add_argument("--body")
    s.add_argument("--kind"); s.add_argument("--status"); s.add_argument("--author", required=True); s.add_argument("--reason", required=True)
    s = sp.add_parser("show"); s.add_argument("ids", nargs="+"); s.add_argument("--comments", default="all", help="all | none | N")
    s = sp.add_parser("list"); s.add_argument("--kind"); s.add_argument("--status"); s.add_argument("--query")
    s.add_argument("--all", action="store_true", help="include merged")
    sp.add_parser("dump")
    s = sp.add_parser("comment"); s.add_argument("id"); s.add_argument("--author", required=True); s.add_argument("--text", required=True)
    s.add_argument("--reply-to", type=int)
    s = sp.add_parser("vote"); s.add_argument("id"); s.add_argument("value", choices=["up", "down"])
    s.add_argument("--author", required=True); s.add_argument("--reason", required=True); s.add_argument("--reply-to", type=int)
    s = sp.add_parser("link"); s.add_argument("frm"); s.add_argument("to"); s.add_argument("--comment", required=True); s.add_argument("--author", required=True)
    s = sp.add_parser("unlink"); s.add_argument("frm"); s.add_argument("to"); s.add_argument("--author", required=True); s.add_argument("--reason", required=True)
    s = sp.add_parser("merge"); s.add_argument("frm"); s.add_argument("into"); s.add_argument("--author", required=True); s.add_argument("--reason", required=True)
    s = sp.add_parser("similar"); s.add_argument("--threshold", type=float, default=0.4); s.add_argument("--ids", nargs="*")
    sp.add_parser("disagreements")
    s = sp.add_parser("queue", help="entries a voter must (re)vote on"); s.add_argument("voter")
    s = sp.add_parser("check"); s.add_argument("--voter", action="append", default=[])
    s = sp.add_parser("export"); s.add_argument("--out", default=os.path.join(A.HERE, "ledger.md"))
    s = sp.add_parser("backup", help="consistent copy of the whole ledger"); s.add_argument("--out", default=os.path.join(A.HERE, "snapshot", "ledger-snapshot.db"))
    s = sp.add_parser("delete-entry", help="admin"); s.add_argument("id"); s.add_argument("--author", required=True); s.add_argument("--reason", required=True)
    s = sp.add_parser("edit-comment", help="admin"); s.add_argument("comment_id", type=int); s.add_argument("--text", required=True)
    s.add_argument("--author", required=True); s.add_argument("--reason", required=True)
    s = sp.add_parser("delete-comment", help="admin"); s.add_argument("comment_id", type=int); s.add_argument("--author", required=True); s.add_argument("--reason", required=True)
    s = sp.add_parser("edit-vote-reason", help="admin"); s.add_argument("id"); s.add_argument("voter"); s.add_argument("--reason", required=True)
    s.add_argument("--author", required=True); s.add_argument("--why", required=True)
    a = p.parse_args()

    ro = a.cmd in ("show", "list", "dump", "similar", "disagreements", "queue", "check", "export", "backup")
    con = A.connect(a.db, readonly=ro)
    try:
        c = a.cmd
        if c == "add":
            refs = [(r.split(":", 1)[0], r.split(":", 1)[1]) for r in a.ref if ":" in r]
            out = A.add(con, a.author, a.kind, a.title, text(a.body) or "", a.status, refs)
        elif c == "update":
            out = A.update(con, a.author, a.id, text(a.reason), a.title, text(a.body), a.kind, a.status)
        elif c == "show":
            out = A.get(con, a.ids, comments=a.comments if a.comments in ("all", "none") else int(a.comments))
        elif c == "list":
            out = A.find(con, a.query, a.kind, a.status, a.all)
        elif c == "dump":
            out = A.dump(con)
        elif c == "comment":
            out = f"comment #{A.comment(con, a.author, a.id, text(a.text), a.reply_to)}"
        elif c == "vote":
            out = A.vote(con, a.author, a.id, a.value, text(a.reason), a.reply_to)
        elif c == "link":
            out = A.link(con, a.author, a.frm, a.to, text(a.comment))
        elif c == "unlink":
            out = "removed" if A.unlink(con, a.author, a.frm, a.to, text(a.reason)) else "no such reference"
        elif c == "merge":
            out = A.merge(con, a.author, a.frm, a.into, text(a.reason))
        elif c == "similar":
            out = A.similar(con, a.threshold, a.ids)
        elif c == "disagreements":
            out = A.disputes(con)
        elif c == "queue":
            out = A.review_queue(con, a.voter)
        elif c == "check":
            out = A.check(con, a.voter)
        elif c == "export":
            with open(a.out, "w", encoding="utf-8") as f:
                f.write(A.export_markdown(con))
            out = f"wrote {a.out}"
        elif c == "backup":
            os.makedirs(os.path.dirname(a.out), exist_ok=True)
            out = f"wrote {A.backup(con, a.out)}"
        elif c == "delete-entry":
            out = A.delete_entry(con, a.author, a.id, text(a.reason))
        elif c == "edit-comment":
            out = A.edit_comment(con, a.author, a.comment_id, text(a.text), text(a.reason))
        elif c == "delete-comment":
            out = A.delete_comment(con, a.author, a.comment_id, text(a.reason))
        elif c == "edit-vote-reason":
            out = A.edit_vote_reason(con, a.author, a.id, a.voter, text(a.reason), text(a.why))
    except A.LedgerError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)

    if a.json or isinstance(out, dict) and c == "check":
        print(json.dumps(out, indent=1, ensure_ascii=False))
    elif isinstance(out, list) and out and isinstance(out[0], dict) and "body" in out[0]:
        for d in out:
            show_entry(d); print()
    elif isinstance(out, list) and out and "a" in out[0]:
        for q in out:
            print(f"{q['score']:.2f}  {q['a']} {q['a_title']}  <->  {q['b']} {q['b_title']}")
    elif isinstance(out, list) and out and "votes" in out[0]:
        for d in out:
            print(line(d)); [print(f"   {v['value']:+d} {v['voter']} (#{v['comment_id']}): {v['reason']}") for v in d["votes"]]
    elif isinstance(out, list):
        for d in out:
            print(line(d))
        print(f"({len(out)} entries)")
    else:
        print(out if not isinstance(out, dict) else json.dumps(out))


if __name__ == "__main__":
    main()
