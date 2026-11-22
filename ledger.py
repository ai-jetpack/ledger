#!/usr/bin/env python3
"""Ledger command line: a thin client of ledger_api (the only code that touches the database).

Entry ids look like L-0001 ("L-1" or "1" also accepted).
--author may appear anywhere and defaults to $LEDGER_AUTHOR.
Text arguments accept @path (read a file) or @- (read stdin). Batch commands read JSON from a file or "-" (stdin).
Run `python ledger.py -h` for commands, `python ledger.py COMMAND -h` for details.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ledger_api as A  # noqa: E402

READS = {"show", "get", "list", "find", "dump", "similar", "disagreements", "queue", "review", "affected", "check", "export", "backup", "map"}


def stdin_text():
    sys.stdin.reconfigure(encoding="utf-8-sig")   # PowerShell pipes may prepend a BOM
    return sys.stdin.read().lstrip("﻿")


def text(v):
    if v is None or not v.startswith("@"):
        return v
    if v == "@-":
        return stdin_text()
    with open(v[1:], encoding="utf-8-sig") as f:
        return f.read()


def load_json(src):
    if src == "-":
        raw = stdin_text()
    else:
        with open(src, encoding="utf-8-sig") as f:
            raw = f.read()
    data = json.loads(raw)
    if not isinstance(data, list):
        raise A.LedgerError("expected a JSON array")
    return data


def refs_of(items):
    out = []
    for r in items or []:
        if ":" not in r:
            raise A.LedgerError(f"--ref must be ID:relationship, got {r!r}")
        i, c = r.split(":", 1)
        out.append((i, c))
    return out


def show_entry(d):
    print(f"{d['id']}  [{d['kind']}/{d['status']}]  score {d['score']:+d} (up {d['up']}, down {d['down']})  by {d['author']}")
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
    hidden = d.get("comment_count", 0) - len(d.get("comments", []))
    if hidden > 0:
        print(f"  ({hidden} older comments not shown)")
    for c in d.get("comments", []):
        rt = f" (reply to #{c['reply_to']})" if c["reply_to"] else ""
        print(f"  #{c['id']} {c['author']}{rt}: {c['text']}")


def line(d):
    m = f" -> merged into {d['merged_into']}" if "merged_into" in d else ""
    return f"{d['id']}  {d['score']:+d}  [{d['kind']}/{d['status']}]  {d['title']}{m}"


def print_dups(con, ids):
    dups = A.duplicates_of(con, ids)
    for p in dups:
        print(f"  possible duplicate ({p['score']:.2f}): {p['a']} {p['a_title']}  <->  {p['b']} {p['b_title']}")


def comments_arg(v):
    return v if v in ("all", "none") else int(v)


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--author", default=argparse.SUPPRESS, help="who is acting (default: $LEDGER_AUTHOR)")
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="print results as JSON")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, parents=[common])
    p.add_argument("--db", default=A.DEFAULT_DB)
    sp = p.add_subparsers(dest="cmd", required=True)

    def cmd(name, help_, aliases=()):
        return sp.add_parser(name, help=help_, aliases=list(aliases), parents=[common])

    s = cmd("add", "create an entry (prints its id and possible duplicates)")
    s.add_argument("--kind", required=True); s.add_argument("--title", required=True); s.add_argument("--body")
    s.add_argument("--status", default="proposed"); s.add_argument("--ref", action="append", help="ID:relationship (repeatable)")
    s = cmd("add-many", "create several entries from a JSON array: [{kind,title,body,status,refs:[{id,comment}]}]; ref id $k = k-th item")
    s.add_argument("src", help="JSON file, or - for stdin")
    s = cmd("set", "create (no --id) or update (--id, needs --reason) an entry")
    s.add_argument("--id"); s.add_argument("--reason"); s.add_argument("--kind"); s.add_argument("--title")
    s.add_argument("--body"); s.add_argument("--status"); s.add_argument("--ref", action="append")
    s = cmd("update", "edit an entry (logged as a comment)")
    s.add_argument("id"); s.add_argument("--reason", required=True); s.add_argument("--title"); s.add_argument("--body")
    s.add_argument("--kind"); s.add_argument("--status")
    s = cmd("show", "entries in full", aliases=["get"])
    s.add_argument("ids", nargs="+"); s.add_argument("--comments", default="all", help="all | none | N (last N)")
    s = cmd("list", "one line per entry", aliases=["find"])
    s.add_argument("query", nargs="?", help="words that must all appear (also searches comments and vote reasons)")
    s.add_argument("--kind"); s.add_argument("--status"); s.add_argument("--by", help="entries authored or edited by this author")
    s.add_argument("--limit", type=int); s.add_argument("--offset", type=int, default=0)
    s.add_argument("--shallow", action="store_true", help="search id, title and body only")
    s.add_argument("--all", action="store_true", help="include merged entries")
    cmd("dump", "every active entry in full")
    s = cmd("comment", "comment on an entry"); s.add_argument("id"); s.add_argument("--text", required=True); s.add_argument("--reply-to", type=int)
    s = cmd("vote", "vote up/down with a reason"); s.add_argument("id"); s.add_argument("value", choices=["up", "down"])
    s.add_argument("--reason", required=True); s.add_argument("--reply-to", type=int)
    s = cmd("vote-many", "several votes from a JSON array: [{id,value,reason,reply_to?}]"); s.add_argument("src", help="JSON file, or - for stdin")
    s = cmd("link", "add or update a reference (a call on the component map when --to-member is given)")
    s.add_argument("frm", metavar="FROM"); s.add_argument("to"); s.add_argument("--comment", required=True)
    s.add_argument("--from-member", default=""); s.add_argument("--to-member", default="")
    s.add_argument("--basis", help="entry that justifies the call; a gap entry draws it as not defined yet")
    s = cmd("links-many", "several references from a JSON array: [{from,to,comment,from_member?,to_member?,basis?}]")
    s.add_argument("src", help="JSON file, or - for stdin")
    s = cmd("unlink", "remove a reference"); s.add_argument("frm", metavar="FROM"); s.add_argument("to"); s.add_argument("--reason", required=True)
    s.add_argument("--from-member"); s.add_argument("--to-member")
    s = cmd("component", "make an entry a box on the component map, or change its map attributes")
    s.add_argument("id"); s.add_argument("--key"); s.add_argument("--name"); s.add_argument("--group", help="req | eng | mem | sys")
    s.add_argument("--types", help="type and element names shown under the title"); s.add_argument("--docs", help='JSON: [["title","url"], ...]')
    s = cmd("components-many", "map attributes from a JSON array: [{id,key,name,group,types?,docs?}]"); s.add_argument("src")
    s = cmd("member", "add or change a row of a component box")
    s.add_argument("id"); s.add_argument("key"); s.add_argument("--label", required=True); s.add_argument("--detail", default="")
    s.add_argument("--form", default="function", help="function | property | pad | event | info | missing")
    s.add_argument("--role", help="api | emit | subscribe | note | missing (box order; default from --form)")
    s = cmd("members-many", "rows from a JSON array: [{id,key,label,detail?,form,role?}]"); s.add_argument("src")
    s = cmd("member-rm", "remove a row (refused while calls use it)"); s.add_argument("id"); s.add_argument("key"); s.add_argument("--reason", required=True)
    cmd("map", "the component map model (boxes, rows in box order, calls, side bar lists) as JSON")
    s = cmd("merge", "merge a duplicate into another entry"); s.add_argument("frm", metavar="FROM"); s.add_argument("into"); s.add_argument("--reason", required=True)
    s = cmd("similar", "candidate duplicate pairs"); s.add_argument("--threshold", type=float, default=0.4); s.add_argument("--ids", nargs="*")
    cmd("disagreements", "entries with split votes, with the comment ids to reply to")
    s = cmd("queue", "ids a voter must (re)vote on"); s.add_argument("voter", nargs="?")
    s = cmd("review", "a voter's whole review queue, in full"); s.add_argument("voter", nargs="?")
    s.add_argument("--comments", default="2", help="all | none | N (default 2)")
    s = cmd("affected", "entries with their linked neighbours (for propagating a change)")
    s.add_argument("ids", nargs="*"); s.add_argument("--query")
    s = cmd("check", "integrity and review status"); s.add_argument("--voter", action="append", default=[])
    s = cmd("export", "write Markdown"); s.add_argument("--out", default=os.path.join(A.HERE, "ledger.md"))
    s = cmd("backup", "consistent copy of the database"); s.add_argument("--out", default=os.path.join(A.HERE, "snapshot", "ledger-snapshot.db"))
    s = cmd("delete-entry", "admin: remove an entry"); s.add_argument("id"); s.add_argument("--reason", required=True)
    s = cmd("edit-comment", "admin"); s.add_argument("comment_id", type=int); s.add_argument("--text", required=True); s.add_argument("--reason", required=True)
    s = cmd("delete-comment", "admin"); s.add_argument("comment_id", type=int); s.add_argument("--reason", required=True)
    s = cmd("edit-vote-reason", "admin"); s.add_argument("id"); s.add_argument("voter"); s.add_argument("--reason", required=True); s.add_argument("--why", required=True)
    s = cmd("reassign-author", "admin: move entries, comments and references from one author to another")
    s.add_argument("--from", dest="old", required=True); s.add_argument("--to", dest="new", required=True); s.add_argument("--reason", required=True)
    return p


ALIASES = {"get": "show", "find": "list"}


def main():
    a = build_parser().parse_args()
    c = ALIASES.get(a.cmd, a.cmd)
    author = getattr(a, "author", None) or os.environ.get("LEDGER_AUTHOR")
    as_json = getattr(a, "json", False)
    con = A.connect(a.db, readonly=c in READS)
    try:
        if c not in READS and not author:
            raise A.LedgerError("no author: pass --author NAME or set LEDGER_AUTHOR")
        if c in ("queue", "review") and not (a.voter or author):
            raise A.LedgerError("no voter: give one or set --author / LEDGER_AUTHOR")
        out = None
        if c == "add":
            out = A.add(con, author, a.kind, a.title, text(a.body) or "", a.status, refs_of(a.ref))
            if not as_json:
                print(out); print_dups(con, [out]); return
        elif c == "add-many":
            out = A.add_many(con, author, load_json(a.src))
            if not as_json:
                print(" ".join(out)); print_dups(con, out); return
        elif c == "set":
            out = A.set_entry(con, author, a.id, text(a.reason), a.kind, a.title, text(a.body), a.status, refs_of(a.ref))
            if not as_json and not a.id:
                print(out); print_dups(con, [out]); return
        elif c == "update":
            out = A.update(con, author, a.id, text(a.reason), a.title, text(a.body), a.kind, a.status)
        elif c == "show":
            out = A.get(con, a.ids, comments=comments_arg(a.comments))
        elif c == "list":
            out = A.find(con, a.query, a.kind, a.status, a.all, a.limit, a.by, a.offset, not a.shallow)
        elif c == "dump":
            out = A.dump(con)
        elif c == "comment":
            out = f"comment #{A.comment(con, author, a.id, text(a.text), a.reply_to)}"
        elif c == "vote":
            out = A.vote(con, author, a.id, a.value, text(a.reason), a.reply_to)
        elif c == "vote-many":
            out = A.vote_many(con, author, load_json(a.src))
            if not as_json:
                for r in out:
                    print(f"{r['id']} score {r['score']:+d}")
                return
        elif c == "link":
            out = A.link(con, author, a.frm, a.to, text(a.comment), a.from_member, a.to_member, a.basis)
        elif c == "links-many":
            out = f"{A.links_many(con, author, load_json(a.src))} references set"
        elif c == "unlink":
            out = "removed" if A.unlink(con, author, a.frm, a.to, text(a.reason), a.from_member, a.to_member) else "no such reference"
        elif c == "component":
            out = A.component_set(con, author, a.id, a.key, a.name, a.group, a.types, json.loads(a.docs) if a.docs else None)
        elif c == "components-many":
            out = f"{A.components_many(con, author, load_json(a.src))} components set"
        elif c == "member":
            out = A.member_set(con, author, a.id, a.key, text(a.label), text(a.detail), a.form, a.role)
        elif c == "members-many":
            out = f"{A.members_many(con, author, load_json(a.src))} members set"
        elif c == "member-rm":
            out = A.member_remove(con, author, a.id, a.key, text(a.reason))
        elif c == "map":
            out = A.map_model(con); as_json = True
        elif c == "merge":
            out = A.merge(con, author, a.frm, a.into, text(a.reason))
        elif c == "similar":
            out = A.similar(con, a.threshold, a.ids)
        elif c == "disagreements":
            out = A.disputes(con)
        elif c == "queue":
            out = A.review_queue(con, a.voter or author)
        elif c == "review":
            out = A.review(con, a.voter or author, comments_arg(a.comments))
            if not out and not as_json:
                print("nothing to review"); return
        elif c == "affected":
            out = A.affected(con, a.ids or None, a.query)
            if not as_json:
                for d in out:
                    print(line(d))
                    for n in d["neighbours"]:
                        print(f"   {n['dir']} {n['id']} [{n['status']}, {n['author']}] {n['title']}: {n['comment']}")
                return
        elif c == "check":
            voters = a.voter or ([author] if author else [])
            out = A.check(con, voters); as_json = True
        elif c == "export":
            with open(a.out, "w", encoding="utf-8") as f:
                f.write(A.export_markdown(con))
            out = f"wrote {a.out}"
        elif c == "backup":
            os.makedirs(os.path.dirname(a.out), exist_ok=True)
            out = f"wrote {A.backup(con, a.out)}"
        elif c == "delete-entry":
            out = A.delete_entry(con, author, a.id, text(a.reason))
        elif c == "edit-comment":
            out = A.edit_comment(con, author, a.comment_id, text(a.text), text(a.reason))
        elif c == "delete-comment":
            out = A.delete_comment(con, author, a.comment_id, text(a.reason))
        elif c == "edit-vote-reason":
            out = A.edit_vote_reason(con, author, a.id, a.voter, text(a.reason), text(a.why))
        elif c == "reassign-author":
            out = A.reassign_author(con, author, a.old, a.new, text(a.reason))
    except (A.LedgerError, json.JSONDecodeError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)

    if as_json:
        print(json.dumps(out, indent=1, ensure_ascii=False))
    elif isinstance(out, list) and out and isinstance(out[0], dict) and "body" in out[0]:
        for d in out:
            show_entry(d); print()
    elif isinstance(out, list) and out and "a" in out[0]:
        for q in out:
            print(f"{q['score']:.2f}  {q['a']} {q['a_title']}  <->  {q['b']} {q['b_title']}")
    elif isinstance(out, list) and out and "votes" in out[0]:
        for d in out:
            print(line(d))
            for v in d["votes"]:
                print(f"   {v['value']:+d} {v['voter']} (reply to #{v['comment_id']}): {v['reason']}")
    elif isinstance(out, list):
        for d in out:
            print(line(d))
        print(f"({len(out)} entries)")
    else:
        print(out if not isinstance(out, dict) else json.dumps(out))


if __name__ == "__main__":
    main()
