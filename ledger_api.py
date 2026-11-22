"""Design ledger API: the only code that touches ledger.db.

Every client (CLI ledger.py, MCP server ledger_mcp.py, viewer ledger_viz.py) goes through these functions.
Functions return plain dicts/lists and raise LedgerError on invalid input.
"""
import os
import re
import sqlite3
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.environ.get("LEDGER_DB", os.path.join(HERE, "ledger.db"))

KINDS = ["requirement", "hardware", "model", "estimate", "measurement", "component", "policy", "technique",
         "kernel", "interface", "decision", "open-question", "non-goal", "milestone", "paper", "finding", "risk"]
STATUSES = ["proposed", "accepted", "open", "deferred", "rejected"]
ADMINS = {"main"}   # only this author may delete entries, edit/delete comments or reassign authorship
USER_DECISION = re.compile(r"\(user\b")   # body marker of an entry that records a user decision, e.g. "Decision (user, 2026-11-21): ..."


def records_user_decision(row):
    """True if the entry records a decision the user stated. Any author may edit such an entry when they see an issue."""
    return bool(USER_DECISION.search(row["body"] or ""))

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'proposed', author TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    merged_into INTEGER REFERENCES entries(id));
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT, entry_id INTEGER NOT NULL REFERENCES entries(id), author TEXT NOT NULL,
    text TEXT NOT NULL, reply_to INTEGER REFERENCES comments(id), created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS votes (
    entry_id INTEGER NOT NULL REFERENCES entries(id), voter TEXT NOT NULL, value INTEGER NOT NULL CHECK (value IN (-1, 1)),
    reason TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (entry_id, voter));
CREATE TABLE IF NOT EXISTS refs (
    from_id INTEGER NOT NULL REFERENCES entries(id), to_id INTEGER NOT NULL REFERENCES entries(id), comment TEXT NOT NULL,
    author TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (from_id, to_id), CHECK (from_id <> to_id));
"""

STOP = set("""a an the and or of to in on for with by is are be as at from that this it its into than then per not no all
each via can will must only also about more most over under so which when while does do their there these those using
used use one two three""".split())


class LedgerError(Exception):
    pass


# ------------------------------------------------------------------ basics
def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_id(i):
    return f"L-{int(i):04d}"


def parse_id(s):
    m = re.fullmatch(r"(?i)\s*(?:l-)?0*(\d+)\s*", str(s))
    if not m:
        raise LedgerError(f"bad entry id {s!r} (expected like L-0001)")
    return int(m.group(1))


def clean(text):
    return (text or "").replace("﻿", "").strip()


def connect(path=DEFAULT_DB, readonly=False):
    if readonly:
        if not os.path.exists(path):
            raise LedgerError(f"no ledger database at {path}")
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=60)
    else:
        new = not os.path.exists(path)
        con = sqlite3.connect(path, timeout=60, isolation_level=None)
        con.execute("PRAGMA journal_mode=WAL")
        if new:
            con.executescript(SCHEMA)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=60000")
    return con


class tx:
    """BEGIN IMMEDIATE transaction: serializes writers, rolls back on error."""
    def __init__(self, con):
        self.con = con

    def __enter__(self):
        self.con.execute("BEGIN IMMEDIATE")
        return self.con

    def __exit__(self, et, ev, tb):
        self.con.execute("ROLLBACK" if et else "COMMIT")
        return False


def _entry(con, eid, active=True):
    row = con.execute("SELECT * FROM entries WHERE id=?", (eid,)).fetchone()
    if not row:
        raise LedgerError(f"{fmt_id(eid)} does not exist")
    if active and row["merged_into"] is not None:
        raise LedgerError(f"{fmt_id(eid)} was merged into {fmt_id(row['merged_into'])}; use that entry")
    return row


def _check(kind=None, status=None):
    if kind is not None and kind not in KINDS:
        raise LedgerError(f"unknown kind {kind!r}; valid: {', '.join(KINDS)}")
    if status is not None and status not in STATUSES:
        raise LedgerError(f"unknown status {status!r}; valid: {', '.join(STATUSES)}")


def _admin(author):
    if author not in ADMINS:
        raise LedgerError(f"only {sorted(ADMINS)} may do this")


def _comment(con, eid, author, text, reply_to=None):
    if reply_to is not None:
        c = con.execute("SELECT entry_id FROM comments WHERE id=?", (reply_to,)).fetchone()
        if not c:
            raise LedgerError(f"comment #{reply_to} does not exist")
        if c["entry_id"] != eid:
            raise LedgerError(f"comment #{reply_to} belongs to {fmt_id(c['entry_id'])}, not {fmt_id(eid)}")
    return con.execute("INSERT INTO comments(entry_id,author,text,reply_to,created_at) VALUES (?,?,?,?,?)",
                       (eid, author, clean(text), reply_to, now())).lastrowid


def _score(con, eid):
    r = con.execute("SELECT COALESCE(SUM(value),0) s, COALESCE(SUM(value=1),0) up, COALESCE(SUM(value=-1),0) down "
                    "FROM votes WHERE entry_id=?", (eid,)).fetchone()
    return r["s"], r["up"], r["down"]


def _link(con, frm, to, comment, author):
    if frm == to:
        raise LedgerError("an entry cannot reference itself")
    _entry(con, frm)
    _entry(con, to)
    if not clean(comment):
        raise LedgerError("a reference needs a comment describing the relationship")
    con.execute("INSERT INTO refs(from_id,to_id,comment,author,created_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(from_id,to_id) DO UPDATE SET comment=excluded.comment, author=excluded.author, "
                "created_at=excluded.created_at", (frm, to, clean(comment), author, now()))


def _tokens(text):
    t = re.sub(r"(\d)([a-z]+)", r"\1 \2", text.lower())
    return {w for w in re.findall(r"[a-z0-9][a-z0-9\-\.]*", t)
            if w not in STOP and (len(w) > 2 or (w.isdigit() and len(w) > 1))}


def _jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


# ------------------------------------------------------------------ reads
def entry_dict(con, row, full=True, comments="all"):
    """comments: 'all' | 'none' | int N (last N)."""
    eid = row["id"]
    s, up, down = _score(con, eid)
    d = {"id": fmt_id(eid), "kind": row["kind"], "title": row["title"], "status": row["status"], "score": s,
         "up": up, "down": down, "author": row["author"], "created_at": row["created_at"],
         "updated_at": row["updated_at"]}
    if row["merged_into"] is not None:
        d["merged_into"] = fmt_id(row["merged_into"])
    if not full:
        return d
    d["body"] = row["body"]
    d["votes"] = [dict(voter=v["voter"], value=v["value"], reason=v["reason"], at=v["created_at"])
                  for v in con.execute("SELECT * FROM votes WHERE entry_id=? ORDER BY voter", (eid,))]
    d["references"] = [dict(id=fmt_id(r["to_id"]), title=r["title"], comment=r["comment"]) for r in con.execute(
        "SELECT r.to_id, r.comment, e.title FROM refs r JOIN entries e ON e.id=r.to_id WHERE r.from_id=? ORDER BY r.to_id", (eid,))]
    d["referenced_by"] = [dict(id=fmt_id(r["from_id"]), title=r["title"], comment=r["comment"]) for r in con.execute(
        "SELECT r.from_id, r.comment, e.title FROM refs r JOIN entries e ON e.id=r.from_id WHERE r.to_id=? ORDER BY r.from_id", (eid,))]
    cs = [dict(id=c["id"], author=c["author"], reply_to=c["reply_to"], text=c["text"], created_at=c["created_at"])
          for c in con.execute("SELECT * FROM comments WHERE entry_id=? ORDER BY id", (eid,))]
    d["comment_count"] = len(cs)
    d["comments"] = [] if comments == "none" else cs if comments == "all" else cs[-int(comments):]
    return d


def get(con, ids, comments="all"):
    return [entry_dict(con, _entry(con, parse_id(i), active=False), comments=comments) for i in ids]


def find(con, query=None, kind=None, status=None, include_merged=False, limit=None, author=None, offset=0, deep=True):
    """Filter entries. query: words that must all appear in id, title, body and (deep=True) comments and vote reasons.
    Paging: offset + limit."""
    q, p = "SELECT * FROM entries WHERE 1=1", []
    if not include_merged: q += " AND merged_into IS NULL"
    if author: q += " AND (author=? OR id IN (SELECT entry_id FROM comments WHERE author=? AND text LIKE '[edit%'))"; p += [author, author]
    if kind: _check(kind=kind); q += " AND kind=?"; p.append(kind)
    if status: _check(status=status); q += " AND status=?"; p.append(status)
    rows = con.execute(q + " ORDER BY id", p).fetchall()
    if query:
        words = [w.lower() for w in query.split()]
        extra = {}
        if deep:
            for eid, t in con.execute("SELECT entry_id, group_concat(text, ' ') FROM comments GROUP BY entry_id"):
                extra[eid] = t or ""
            for eid, t in con.execute("SELECT entry_id, group_concat(reason, ' ') FROM votes GROUP BY entry_id"):
                extra[eid] = extra.get(eid, "") + " " + (t or "")
        rows = [r for r in rows if all(w in (fmt_id(r["id"]) + " " + r["title"] + " " + r["body"] + " " +
                                             extra.get(r["id"], "")).lower() for w in words)]
    rows = rows[offset:offset + limit] if limit else rows[offset:]
    return [entry_dict(con, r, full=False) for r in rows]


def review(con, voter, comments=2):
    """The voter's whole review queue in one call: every entry to (re)vote on, in full."""
    rows = con.execute(
        "SELECT e.* FROM entries e LEFT JOIN votes v ON v.entry_id=e.id AND v.voter=? "
        "WHERE e.merged_into IS NULL AND (v.voter IS NULL OR v.created_at < e.updated_at) ORDER BY e.id", (voter,)).fetchall()
    return [entry_dict(con, r, comments=comments) for r in rows]


def affected(con, ids=None, query=None):
    """Entries named (or matching a query) with their linked neighbours, for propagating a change in one read."""
    targets = [parse_id(i) for i in ids] if ids else [parse_id(d["id"]) for d in find(con, query)] if query else []
    out = []
    for eid in targets:
        d = entry_dict(con, _entry(con, eid, active=False), full=False)
        d["neighbours"] = [dict(dir="->", id=fmt_id(r["to_id"]), title=r["title"], status=r["status"], author=r["author"], comment=r["comment"])
                           for r in con.execute("SELECT r.to_id, r.comment, e.title, e.status, e.author FROM refs r JOIN entries e "
                                                "ON e.id=r.to_id WHERE r.from_id=? ORDER BY r.to_id", (eid,))]
        d["neighbours"] += [dict(dir="<-", id=fmt_id(r["from_id"]), title=r["title"], status=r["status"], author=r["author"], comment=r["comment"])
                            for r in con.execute("SELECT r.from_id, r.comment, e.title, e.status, e.author FROM refs r JOIN entries e "
                                                 "ON e.id=r.from_id WHERE r.to_id=? ORDER BY r.from_id", (eid,))]
        out.append(d)
    return out


def dump(con, comments="all"):
    return [entry_dict(con, r, comments=comments)
            for r in con.execute("SELECT * FROM entries WHERE merged_into IS NULL ORDER BY id").fetchall()]


def review_queue(con, voter):
    """Active entries the voter has not voted on, or that changed after the voter's vote."""
    rows = con.execute(
        "SELECT e.* FROM entries e LEFT JOIN votes v ON v.entry_id=e.id AND v.voter=? "
        "WHERE e.merged_into IS NULL AND (v.voter IS NULL OR v.created_at < e.updated_at) ORDER BY e.id", (voter,)).fetchall()
    return [entry_dict(con, r, full=False) for r in rows]


def disputes(con):
    """Entries with split votes, each vote with the id of the voter's latest vote comment (to reply to)."""
    out = []
    for r in con.execute("SELECT e.* FROM entries e JOIN votes v ON v.entry_id=e.id WHERE e.merged_into IS NULL "
                         "GROUP BY e.id HAVING MIN(v.value) <> MAX(v.value) ORDER BY e.id").fetchall():
        d = entry_dict(con, r, full=False)
        d["votes"] = []
        for v in con.execute("SELECT * FROM votes WHERE entry_id=? ORDER BY voter", (r["id"],)):
            c = con.execute("SELECT id FROM comments WHERE entry_id=? AND author=? AND (text LIKE '[upvote%' OR text LIKE "
                            "'[downvote%') ORDER BY id DESC LIMIT 1", (r["id"], v["voter"])).fetchone()
            d["votes"].append(dict(voter=v["voter"], value=v["value"], reason=v["reason"], comment_id=c["id"] if c else None))
        out.append(d)
    return out


def similar(con, threshold=0.4, ids=None):
    """Candidate duplicate pairs by word overlap; if ids given, only pairs involving them."""
    rows = con.execute("SELECT * FROM entries WHERE merged_into IS NULL ORDER BY id").fetchall()
    focus = {parse_id(i) for i in ids} if ids else None
    toks = [(r, _tokens(r["title"]), _tokens(r["title"] + " " + r["body"])) for r in rows]
    pairs = []
    for i in range(len(toks)):
        for j in range(i + 1, len(toks)):
            a, b = toks[i][0]["id"], toks[j][0]["id"]
            if focus and a not in focus and b not in focus:
                continue
            ti, tx_ = _jaccard(toks[i][1], toks[j][1]), _jaccard(toks[i][2], toks[j][2])
            if max(ti, tx_) >= threshold:
                pairs.append(dict(score=round(max(ti, tx_), 2), a=fmt_id(a), a_title=toks[i][0]["title"],
                                  b=fmt_id(b), b_title=toks[j][0]["title"]))
    return sorted(pairs, key=lambda p: -p["score"])


def check(con, voters=()):
    act = con.execute("SELECT COUNT(*) FROM entries WHERE merged_into IS NULL").fetchone()[0]
    res = {"active": act}
    res["refs_touching_merged"] = con.execute(
        "SELECT COUNT(*) FROM refs r JOIN entries a ON a.id=r.from_id JOIN entries b ON b.id=r.to_id "
        "WHERE a.merged_into IS NOT NULL OR b.merged_into IS NOT NULL").fetchone()[0]
    res["unlinked"] = [fmt_id(r[0]) for r in con.execute(
        "SELECT id FROM entries e WHERE merged_into IS NULL AND NOT EXISTS (SELECT 1 FROM refs WHERE from_id=e.id OR to_id=e.id)")]
    res["unvoted"] = [fmt_id(r[0]) for r in con.execute(
        "SELECT id FROM entries e WHERE merged_into IS NULL AND NOT EXISTS (SELECT 1 FROM votes WHERE entry_id=e.id)")]
    res["review_queue"] = {v: [d["id"] for d in review_queue(con, v)] for v in voters}
    res["split"] = [d["id"] for d in disputes(con)]
    titles = {}
    for r in con.execute("SELECT id, title FROM entries WHERE merged_into IS NULL"):
        titles.setdefault(r["title"].strip().lower(), []).append(fmt_id(r["id"]))
    res["identical_titles"] = [ids for ids in titles.values() if len(ids) > 1]
    return res


# ------------------------------------------------------------------ writes
def _insert(con, author, kind, title, body, status, refs, batch_ids=()):
    """Insert one entry inside an open transaction. A ref id "$k" points at the k-th entry of the same batch."""
    _check(kind, status or "proposed")
    if not clean(title):
        raise LedgerError("title is required")
    t = now()
    eid = con.execute("INSERT INTO entries(kind,title,body,status,author,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                      (kind, clean(title), clean(body), status or "proposed", author, t, t)).lastrowid
    for to, c in refs:
        if str(to).startswith("$"):
            k = int(str(to)[1:])
            if k >= len(batch_ids):
                raise LedgerError(f"reference {to} points at a batch entry that is not created yet")
            to = batch_ids[k]
        _link(con, eid, parse_id(to), c, author)
    return eid


def add(con, author, kind, title, body="", status="proposed", refs=()):
    """refs: iterable of (id, comment). Returns the new id."""
    with tx(con):
        eid = _insert(con, author, kind, title, body, status, refs)
    return fmt_id(eid)


def add_many(con, author, items):
    """Create several entries in one transaction (all or nothing).
    items: [{kind, title, body?, status?, refs: [{id, comment}]}]; a ref id "$k" means the k-th item of this batch."""
    ids = []
    with tx(con):
        for n, it in enumerate(items):
            try:
                refs = [(r["id"], r["comment"]) for r in it.get("refs", [])]
                ids.append(_insert(con, author, it.get("kind"), it.get("title"), it.get("body", ""), it.get("status"), refs, ids))
            except (LedgerError, KeyError) as e:
                raise LedgerError(f"item {n} ({it.get('title', '?')}): {e}")
    return [fmt_id(i) for i in ids]


def duplicates_of(con, ids, threshold=0.4):
    """Near-duplicate candidates of the given entries (same word-overlap test as similar)."""
    return similar(con, threshold, ids)


def update(con, author, eid, reason, title=None, body=None, kind=None, status=None):
    eid = parse_id(eid)
    _check(kind, status)
    changes = {k: clean(v) for k, v in (("title", title), ("body", body), ("kind", kind), ("status", status)) if v is not None}
    if not changes:
        raise LedgerError("nothing to update")
    if not clean(reason):
        raise LedgerError("a reason is required")
    with tx(con):
        row = _entry(con, eid)
        if author not in ADMINS and row["author"] != author and not records_user_decision(row):
            raise LedgerError(f"{fmt_id(eid)} belongs to {row['author']}; comment on it instead")
        sets = ", ".join(f"{k}=?" for k in changes) + ", updated_at=?"
        con.execute(f"UPDATE entries SET {sets} WHERE id=?", (*changes.values(), now(), eid))
        _comment(con, eid, author, f"[edit: {', '.join(changes)}] {clean(reason)}")
    return fmt_id(eid)


def comment(con, author, eid, text, reply_to=None):
    eid = parse_id(eid)
    if not clean(text):
        raise LedgerError("empty comment")
    with tx(con):
        _entry(con, eid)
        return _comment(con, eid, author, text, reply_to)


def _vote(con, author, eid, value, reason, reply_to=None):
    eid = parse_id(eid)
    val = {"up": 1, "down": -1, 1: 1, -1: -1}.get(value)
    if val is None:
        raise LedgerError("value must be 'up' or 'down'")
    if not clean(reason):
        raise LedgerError("a vote needs a reason")
    _entry(con, eid)
    prev = con.execute("SELECT value FROM votes WHERE entry_id=? AND voter=?", (eid, author)).fetchone()
    con.execute("INSERT INTO votes(entry_id,voter,value,reason,created_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(entry_id,voter) DO UPDATE SET value=excluded.value, reason=excluded.reason, "
                "created_at=excluded.created_at", (eid, author, val, clean(reason), now()))
    tag = "upvote" if val > 0 else "downvote"
    if prev and prev["value"] != val:
        tag += f", changed from {'upvote' if prev['value'] > 0 else 'downvote'}"
    elif prev:
        tag += ", reaffirmed"
    _comment(con, eid, author, f"[{tag}] {clean(reason)}", reply_to)
    s, up, down = _score(con, eid)
    return {"id": fmt_id(eid), "score": s, "up": up, "down": down}


def vote(con, author, eid, value, reason, reply_to=None):
    with tx(con):
        return _vote(con, author, eid, value, reason, reply_to)


def vote_many(con, author, votes):
    """Several votes in one transaction (all or nothing). votes: [{id, value, reason, reply_to?}]."""
    out = []
    with tx(con):
        for n, v in enumerate(votes):
            try:
                out.append(_vote(con, author, v["id"], v["value"], v["reason"], v.get("reply_to")))
            except (LedgerError, KeyError) as e:
                raise LedgerError(f"vote {n} ({v.get('id', '?')}): {e}")
    return out


def set_entry(con, author, eid=None, reason=None, kind=None, title=None, body=None, status=None, refs=()):
    """Create (no id) or update (id given; reason required) in one verb."""
    if eid is None:
        return add(con, author, kind, title, body or "", status or "proposed", refs)
    out = update(con, author, eid, reason, title, body, kind, status)
    for to, c in refs:
        link(con, author, eid, to, c)
    return out


def link(con, author, frm, to, comment_text):
    with tx(con):
        _link(con, parse_id(frm), parse_id(to), comment_text, author)
    return f"{fmt_id(parse_id(frm))} -> {fmt_id(parse_id(to))}"


def unlink(con, author, frm, to, reason):
    frm, to = parse_id(frm), parse_id(to)
    with tx(con):
        n = con.execute("DELETE FROM refs WHERE from_id=? AND to_id=?", (frm, to)).rowcount
        if n:
            _comment(con, frm, author, f"[unlink {fmt_id(to)}] {clean(reason)}")
    return bool(n)


def merge(con, author, frm, into, reason):
    src, dst = parse_id(frm), parse_id(into)
    if src == dst:
        raise LedgerError("cannot merge an entry into itself")
    with tx(con):
        s = _entry(con, src)
        _entry(con, dst)
        for c in con.execute("SELECT * FROM comments WHERE entry_id=? ORDER BY id", (src,)).fetchall():
            con.execute("INSERT INTO comments(entry_id,author,text,reply_to,created_at) VALUES (?,?,?,?,?)",
                        (dst, c["author"], f"[from {fmt_id(src)}] {c['text']}", None, c["created_at"]))
        for r in con.execute("SELECT * FROM refs WHERE from_id=?", (src,)).fetchall():
            if r["to_id"] != dst:
                con.execute("INSERT OR IGNORE INTO refs VALUES (?,?,?,?,?)", (dst, r["to_id"], r["comment"], r["author"], r["created_at"]))
        for r in con.execute("SELECT * FROM refs WHERE to_id=?", (src,)).fetchall():
            if r["from_id"] != dst:
                con.execute("INSERT OR IGNORE INTO refs VALUES (?,?,?,?,?)", (r["from_id"], dst, r["comment"], r["author"], r["created_at"]))
        con.execute("DELETE FROM refs WHERE from_id=? OR to_id=?", (src, src))
        _, up, down = _score(con, src)
        con.execute("DELETE FROM votes WHERE entry_id=?", (src,))
        t = now()
        con.execute("UPDATE entries SET merged_into=?, updated_at=? WHERE id=?", (dst, t, src))
        con.execute("UPDATE entries SET updated_at=? WHERE id=?", (t, dst))   # puts it back in review queues
        _comment(con, dst, author, f"[merge] {fmt_id(src)} \"{s['title']}\" merged into this entry "
                                   f"(its votes were up {up}, down {down}). {clean(reason)}")
    return f"{fmt_id(src)} merged into {fmt_id(dst)}"


# ------------------------------------------------------------------ admin (main only)
def reassign_author(con, author, old, new, reason):
    """Move authorship of entries, comments and references from `old` to `new`. Logged on each entry `old` authored."""
    _admin(author)
    old, new = clean(old), clean(new)
    if not old or not new or old == new:
        raise LedgerError("give two different author names")
    if not clean(reason):
        raise LedgerError("a reason is required")
    with tx(con):
        owned = [r[0] for r in con.execute("SELECT id FROM entries WHERE author=?", (old,))]
        n_e = con.execute("UPDATE entries SET author=? WHERE author=?", (new, old)).rowcount
        n_c = con.execute("UPDATE comments SET author=? WHERE author=?", (new, old)).rowcount
        n_r = con.execute("UPDATE refs SET author=? WHERE author=?", (new, old)).rowcount
        for eid in owned:
            _comment(con, eid, author, f"[author: {old} -> {new}] {clean(reason)}")
    return f"reassigned {old} -> {new}: {n_e} entries, {n_c} comments, {n_r} references"



def delete_entry(con, author, eid, reason):
    """Remove an entry completely, with its links, votes and comments. Logged on each entry that linked to it."""
    _admin(author)
    eid = parse_id(eid)
    with tx(con):
        row = _entry(con, eid, active=False)
        linked = {r[0] for r in con.execute("SELECT from_id FROM refs WHERE to_id=? UNION SELECT to_id FROM refs WHERE from_id=?", (eid, eid))}
        con.execute("DELETE FROM refs WHERE from_id=? OR to_id=?", (eid, eid))
        con.execute("DELETE FROM votes WHERE entry_id=?", (eid,))
        con.execute("UPDATE comments SET reply_to=NULL WHERE reply_to IN (SELECT id FROM comments WHERE entry_id=?)", (eid,))
        con.execute("DELETE FROM comments WHERE entry_id=?", (eid,))
        con.execute("UPDATE entries SET merged_into=NULL WHERE merged_into=?", (eid,))
        con.execute("DELETE FROM entries WHERE id=?", (eid,))
        for other in linked:
            if con.execute("SELECT 1 FROM entries WHERE id=?", (other,)).fetchone():
                _comment(con, other, author, f"[deleted {fmt_id(eid)}, link removed] {clean(reason)}")
    return f"deleted {fmt_id(eid)} ({row['title']}); unlinked {len(linked)} entries"


def edit_comment(con, author, comment_id, text, reason):
    _admin(author)
    with tx(con):
        if not con.execute("SELECT 1 FROM comments WHERE id=?", (comment_id,)).fetchone():
            raise LedgerError(f"comment #{comment_id} does not exist")
        con.execute("UPDATE comments SET text=? WHERE id=?", (f"{clean(text)} [edited by {author}: {clean(reason)}]", comment_id))
    return f"comment #{comment_id} edited"


def delete_comment(con, author, comment_id, reason):
    _admin(author)
    with tx(con):
        c = con.execute("SELECT entry_id FROM comments WHERE id=?", (comment_id,)).fetchone()
        if not c:
            raise LedgerError(f"comment #{comment_id} does not exist")
        con.execute("UPDATE comments SET reply_to=NULL WHERE reply_to=?", (comment_id,))
        con.execute("DELETE FROM comments WHERE id=?", (comment_id,))
    return f"comment #{comment_id} deleted from {fmt_id(c['entry_id'])}"


def edit_vote_reason(con, author, eid, voter, reason, why):
    _admin(author)
    eid = parse_id(eid)
    with tx(con):
        n = con.execute("UPDATE votes SET reason=? WHERE entry_id=? AND voter=?", (clean(reason), eid, voter)).rowcount
        if not n:
            raise LedgerError(f"{voter} has no vote on {fmt_id(eid)}")
        _comment(con, eid, author, f"[vote reason of {voter} edited] {clean(why)}")
    return f"vote reason of {voter} on {fmt_id(eid)} edited"


# ------------------------------------------------------------------ export
def backup(con, path):
    """Write a consistent copy of the whole ledger to `path` (SQLite online backup; safe while others write)."""
    if os.path.exists(path):
        os.remove(path)
    dst = sqlite3.connect(path)
    try:
        con.backup(dst)
    finally:
        dst.close()
    return path


def snapshot(con):
    return {"generated_at": now(), "kinds": KINDS, "statuses": STATUSES,
            "entries": [entry_dict(con, r) for r in con.execute("SELECT * FROM entries ORDER BY id").fetchall()]}


def version(con):
    return con.execute(
        "SELECT (SELECT COUNT(*) FROM entries) || '.' || (SELECT COALESCE(MAX(updated_at),'') FROM entries) || '.' ||"
        " (SELECT COALESCE(MAX(id),0) FROM comments) || '.' || (SELECT COUNT(*) FROM comments) || '.' ||"
        " (SELECT COUNT(*) FROM refs) || '.' || (SELECT COALESCE(MAX(created_at),'') FROM refs) || '.' ||"
        " (SELECT COUNT(*) FROM votes) || '.' || (SELECT COALESCE(SUM(value),0) FROM votes) || '.' ||"
        " (SELECT COALESCE(MAX(created_at),'') FROM votes)").fetchone()[0]


def export_markdown(con, title="Design Ledger"):
    ds = dump(con)
    merged = con.execute("SELECT id, title, merged_into FROM entries WHERE merged_into IS NOT NULL ORDER BY id").fetchall()
    L = [f"# {title}", "", f"Exported {now()}. {len(ds)} active entries, {len(merged)} merged.", "",
         "## Index", "", "| ID | Kind | Status | Score | Title |", "| --- | --- | --- | --- | --- |"]
    L += [f"| [{d['id']}](#{d['id'].lower()}) | {d['kind']} | {d['status']} | {d['score']:+d} | {d['title']} |" for d in ds]
    L.append("")
    for kind in KINDS:
        group = [d for d in ds if d["kind"] == kind]
        if not group:
            continue
        L += [f"## {kind}", ""]
        for d in group:
            L += [f"### {d['id']}", "", f"**{d['title']}** · {d['status']} · score {d['score']:+d} (up {d['up']}, down {d['down']})", ""]
            if d["body"]:
                L += [d["body"], ""]
            for label, key, arrow in (("References", "references", ""), ("Referenced by", "referenced_by", "")):
                if d[key]:
                    L.append(f"{label}:")
                    L += [f"- [{r['id']}](#{r['id'].lower()}) {r['title']} — {r['comment']}" for r in d[key]]
                    L.append("")
            if d["comments"]:
                L.append("Comments:")
                L += [f"- #{c['id']}{' ↳ #' + str(c['reply_to']) if c['reply_to'] else ''} **{c['author']}**: {c['text']}" for c in d["comments"]]
                L.append("")
    if merged:
        L += ["## Merged entries", ""] + [f"- {fmt_id(m['id'])} {m['title']} → {fmt_id(m['merged_into'])}" for m in merged]
    return "\n".join(L) + "\n"
