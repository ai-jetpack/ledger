---
name: ledger
description: Work with the voted, linked ledger (entries with votes, threaded comments and annotated references). Use to add or update entries, review and vote, run an adversarial debate over a disagreement, find and merge duplicates, or visualize the ledger. Triggers on "ledger", "add an entry", "vote on", "review the ledger", "resolve the disagreement", "dedupe".
---

# Ledger

A ledger holds any number of entries. Each entry has an id (`L-0001`), a kind, a title, a body, a status, a vote count (every vote carries a reason), threaded comments, and references to other entries (each reference has a comment naming the relationship).

## How to access it

- **Only through the API, never the database file.** No SQL, no opening `ledger.db`, no editing exports. Everything goes through `ledger_api.py`, which has two front ends:
  1. **MCP tools** (`ledger_*`), if your session has them. Preferred: the author is fixed by the server, results are compact, and edits to other authors' entries are refused.
  2. **Command line**, from the repository root: `python ledger.py <command> --author NAME ...` (`python ledger.py -h`). Text arguments accept `@path` to read from a file, which avoids shell quoting problems for long text.
- Tool mapping: `queue` = `ledger_queue`, `show` = `ledger_get`, `list` = `ledger_find`, `disagreements` = `ledger_disputes`, `similar` = `ledger_similar`, `add`, `update`, `comment`, `vote`, `link`, `unlink`, `merge` have the same names.
- To see the ledger: `python ledger_viz.py serve` and open http://127.0.0.1:8765 (live while others write).

## Writing entries

- **One atomic element per entry** (a requirement, a component, a measurement, a decision, an open question...). Two things that can be accepted or rejected separately are two entries.
- Title: specific and unique, at most about 80 characters. Body: the specifics, with numbers, units and sources, and why it matters.
- Kinds: `requirement hardware model estimate measurement component policy technique kernel interface decision open-question non-goal milestone paper finding risk`. Statuses: `proposed accepted open deferred rejected`. Things decided are `accepted`, questions are `open`, ruled-out ideas are `rejected` (kept, not deleted, so the reasoning stays visible).
- **Every entry references at least one other entry**, and the reference comment names the relationship precisely: "implements", "depends on", "constrained by", "justified by", "measures the input of", "alternative to", "part of", "decided by". A bare "related" is not acceptable.
- **Search before adding** (`ledger_find` with a few words) so you do not create a duplicate.
- Edit only your own entries (`update` needs a reason and is logged as a comment). Comment on anyone else's.
- Entries authored or edited by `user` record the user's decisions and are authoritative: you cannot edit them, and you never vote one down for the decision itself, only for recording it wrongly or getting a consequence wrong. List them with `ledger_find` and `author=user`.

## Voting

Vote up or down on every entry you review, with a reason that names the specific figure, entry or link at issue ("looks good" is not a reason).
- **Up:** correct, specific, atomic, right kind and status, links accurate.
- **Down:** wrong or unsupported figure, contradiction with another entry, too vague, not atomic, wrong kind or status, wrong or missing links, or a duplicate (start the reason with `[duplicate of L-XXXX]`).
- One vote per voter per entry; voting again replaces the old one.

## Procedures

**REVIEW** (work through what changed)
1. `ledger_queue` lists entries you have not voted on or that changed after your vote.
2. For each, `ledger_get` it (the last 2 comments are usually enough) and vote.
3. Done when the queue is empty.

**DEBATE** (two voters disagree)
1. `ledger_disputes` lists split entries with each vote and the comment id to reply to.
2. `ledger_get` the entry with all comments, then reply in its thread (`reply_to` = the other side's vote comment). Engage their specific argument with evidence. Do not concede to be agreeable, and do not defend an error once the evidence is against you.
3. End the reply with exactly one line:
   - `STANCE: HOLD`: you still disagree; say what evidence would change your mind.
   - `STANCE: CONCEDE`: then re-vote to match.
   - `STANCE: AMEND`: only for your own entry; fix it with `update` and keep your vote.
4. Repeat until no entry is disputed.

**DUPLICATES**
1. `ledger_similar` (optionally limited to new ids) lists candidate pairs by word overlap. Judge by meaning: two entries are duplicates only if they record the same element. A fact and the policy built on it, or evidence and the decision it supports, are distinct if linked.
2. Post `[dup-check L-XXXX/L-YYYY] DISTINCT|DUPLICATE: reason` as a comment on the lower id; link distinct pairs that are not yet linked.
3. Merge only after all reviewers agree, naming the surviving entry: `ledger_merge from into reason`. Merging moves comments and references and redirects links.

**PROPAGATE** (a decision or fact changed)
1. `ledger_find` the entries it affects.
2. Update yours (reason cites the change); comment on others'.
3. Run REVIEW so votes match the new text.

**FILL** (turn a body of material into entries)
Add entries with their references, cross-link entries that belong together, then REVIEW.

## Keeping usage small

Fetch only the entries you need; never read the whole ledger. Use `ledger_queue` and `ledger_disputes` as your work lists. Prefer `comments=2` when reading an entry unless you are in a debate.
