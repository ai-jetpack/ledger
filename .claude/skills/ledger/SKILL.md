---
name: ledger
description: Work with the voted, linked ledger (entries with votes, threaded comments and annotated references). Use to add or update entries, review and vote, run an adversarial debate over a disagreement, find and merge duplicates, propagate a change, or visualize the ledger. Triggers on "ledger", "add an entry", "vote on", "review the ledger", "resolve the disagreement", "dedupe".
---

# Ledger

A ledger holds any number of entries. Each entry has an id (`L-0001`), a kind, a title, a body, a status, a vote count (every vote carries a reason), threaded comments, and references to other entries (each reference has a comment naming the relationship).

## Access: the API only

- **Never read or write the data directly**: no SQL, no opening `ledger.db`, no scripts that touch it, no reading or editing exports. Every read and write goes through the command line `python ledger.py <command> ...` from the repository root, which calls the API (`ledger_api.py`). `-h` lists commands, `<command> -h` their options.
- **If the API is missing something, or a task takes more calls than it should, stop and propose an API change** to the user instead of working around it.
- Set your name once: `LEDGER_AUTHOR=<you>` in the environment (PowerShell: `$env:LEDGER_AUTHOR='alpha'`); `--author NAME` can also appear anywhere on the line.
- Long text: `--body @-` reads stdin (pipe it in: no temporary files, no quoting problems), `--body @file` reads a file. Batches read a JSON array from stdin (`-`) or a file.
- The API enforces: you can edit your own entries and entries that record a user decision; comment on everyone else's. `main` is the administrator: it may edit any entry, delete entries, edit or delete comments and reassign authorship.
- To see the ledger: `python ledger_viz.py serve`, then http://127.0.0.1:8765 (live while others write).

| Need | Command |
| --- | --- |
| Your review work, in full | `review` (`--comments N`, default 2) |
| Just the ids to review | `queue` |
| Read entries | `get IDS --comments N` |
| Search titles, bodies, comments and vote reasons (paged) | `find "words" --limit N --offset N` (`--kind`, `--status`, `--by alpha`) |
| An entry and all its neighbours | `affected IDS` or `affected --query "words"` |
| Create one / many | `add --kind K --title T --body @- --ref ID:relationship` / `add-many -` |
| Create or edit with one verb | `set ...` (no `--id`: create; `--id ID --reason R`: update) |
| Edit your entry, or a user-decision entry | `update ID --reason R [--title --body --kind --status]` |
| Vote one / many | `vote ID up\|down --reason R` / `vote-many -` |
| Comment, link, unlink, merge | `comment ID --text @- [--reply-to N]`, `link FROM TO --comment C`, `unlink FROM TO --reason R`, `merge FROM INTO --reason R` |
| Split votes / candidate duplicates | `disagreements` / `similar [--ids IDS]` |

Batch formats:
- add-many: `[{"kind": "...", "title": "...", "body": "...", "status": "proposed", "refs": [{"id": "L-0012", "comment": "implements"}, {"id": "$0", "comment": "part of"}]}]`. A reference id `$k` points at the k-th item of the same batch. All or nothing.
- vote-many: `[{"id": "L-0012", "value": "up", "reason": "..."}]`. All or nothing.

## Writing entries

- **One atomic element per entry** (a requirement, a component, a measurement, a decision, an open question...). Two things that can be accepted or rejected separately are two entries.
- Title: specific and unique, at most about 80 characters. Body: the specifics, with numbers, units and sources, and why it matters.
- Kinds: `requirement hardware model estimate measurement component policy technique kernel interface decision open-question non-goal milestone paper finding risk assumption gap future-work`. `gap` = something not defined yet, `assumption` = an interpretation to confirm; both, with open `open-question`s, appear in the component map's side bar. `future-work` = a possible later improvement, not planned now (status `deferred`). Statuses: `proposed accepted open deferred rejected`. Things decided are `accepted`, questions are `open`, ruled-out ideas are `rejected` (kept, not deleted, so the reasoning stays visible).
- **Every entry references at least one other entry**, and the reference comment names the relationship precisely: "implements", "depends on", "constrained by", "justified by", "measures the input of", "alternative to", "part of", "decided by". A bare "related" is not acceptable.
- Search before adding (`find` with a few words). `add` and `add-many` also report possible duplicates of what they just created: check each one, and if it is a real duplicate, say so (see DUPLICATES).
- Edit your own entries (`update` needs a reason and is logged as a comment). Comment on anyone else's.
- The user never writes in the ledger; `main` records the user's decisions, and their body is marked `(user`, for example "Decision (user, 2026-11-21): ...". They are authoritative: never vote one down for the decision itself, only for recording it wrongly or getting a consequence wrong. When you see such an issue, fix it yourself with `update` (the reason names the issue); keep the decision as the user stated it. List them with `find "(user"`.

## Voting

Vote up or down on every entry you review, with a reason that names the specific figure, entry or link at issue ("looks good" is not a reason). Each reason is written for its entry: one shared or template reason across many entries is not acceptable.
- **Up:** correct, specific, atomic, right kind and status, links accurate.
- **Down:** wrong or unsupported figure, contradiction with another entry, too vague, not atomic, wrong kind or status, wrong or missing links, or a duplicate (start the reason with `[duplicate of L-XXXX]`).
- One vote per voter per entry; voting again replaces the old one.

## Procedures (fewest calls)

**REVIEW**: one read, one write.
1. `review` returns every entry you have not voted on or that changed since your vote, in full (last 2 comments each).
2. Judge them all, then send every vote in one `vote-many`.
3. Done when `review` says nothing to review.

**DEBATE** (two voters disagree)
1. `disagreements` lists split entries with each vote and the comment id to reply to.
2. `get` the entry with all comments, then reply in its thread (`comment ID --reply-to N`, N = the other side's vote comment). Engage their specific argument with evidence. Do not concede to be agreeable, and do not defend an error once the evidence is against you.
3. End the reply with exactly one line:
   - `STANCE: HOLD`: you still disagree; say what evidence would change your mind.
   - `STANCE: CONCEDE`: then re-vote to match.
   - `STANCE: AMEND`: only for your own entry; fix it with `update` and keep your vote.
4. Repeat until no entry is disputed.

**DUPLICATES**
1. `similar` (optionally limited to new ids) lists candidate pairs by word overlap. Judge by meaning: two entries are duplicates only if they record the same element. A fact and the policy built on it, or evidence and the decision it supports, are distinct if linked.
2. Post `[dup-check L-XXXX/L-YYYY] DISTINCT|DUPLICATE: reason` as a comment on the lower id; link distinct pairs that are not yet linked.
3. Merge only after all reviewers agree, naming the surviving entry: `merge FROM INTO --reason ...`. Merging moves comments and references and redirects links.

**PROPAGATE** (a decision or fact changed)
1. `affected` with the changed entry's id (or a query) returns it with every linked entry, its status and author: one read.
2. Update yours (reason cites the change); comment on others'.
3. Run REVIEW so votes match the new text.

**FILL** (turn a body of material into entries)
1. `find` once or twice for what already exists.
2. Send all new entries in one `add-many`, cross-linking them with `$k` references.
3. Check the reported possible duplicates, then REVIEW.

## Component map

The component map is generated from the ledger (viewer: http://127.0.0.1:8765/components; model: `map`). Never draw or edit a map separately: change the ledger and the map follows.
- **Box** = an entry with component attributes: `component ID --key K --name "Display name" --group req|eng|mem|sys [--types "MoeFoo · \"moefoo\""] [--docs '[["title","url"]]']` (batch: `components-many -`).
- **Row** = a member of that entry: `member ID KEY --label L [--detail D] --form function|property|pad|event|info|missing [--role api|emit|subscribe|note|missing]` (batch: `members-many -`; remove: `member-rm ID KEY --reason R`, refused while a call uses it). The role orders the box: APIs first, then events emitted, then events subscribed, then notes and missing items; the default role follows the form (events default to `emit`; a handler such as `on "moe-turn-end"` is `--form event --role subscribe`). There is no order field.
- **Call (arrow)** = a reference anchored on members: `link FROM TO --comment "what passes" --to-member KEY [--from-member KEY] [--basis ID]` (batch: `links-many -` with `from, to, comment, from_member, to_member, basis`). `--basis` is the entry that justifies the call; when it is a `gap`, the arrow is drawn as not defined yet. Plain references without members are design links and are not drawn.
- **Tier** = the box's row in the layered view, top to bottom: `app` (the executable), `service` (what it creates and serves through: API server, pipeline, model manager), `element` (GStreamer plugins: elements, tracer), `engine` (objects inside an element), `resource` (memory, weights, caches, kernels, model files), `platform` (the machine). Set it with `component ID --tier T` (or `tier` in `components-many`). It is a classification, not an order.
- The layout is automatic (columns by call depth, or rows by tier with "By layer"); there are no coordinates in the ledger.
- **Issues** = open gaps, unconfirmed assumptions and open questions. The side bar lists them all; a selected box's details panel lists the issues linked to it (by a reference, or as the basis of one of its calls), and every issue shows the names of its boxes. Link each issue to the boxes it concerns and name those boxes in its title by their display name on the map ("Platform description: no query of free VRAM ..."), so the user finds it under the same name in both places.
- The user can comment on a side-bar issue from the map; those comments have author `user`. Treat them as the user's input: main records any decision they contain.
- `check` also reports components without members, components without a tier and calls to members that do not exist.

## Keeping usage small

Use `review`, `disagreements` and `affected` as your work lists; never read the whole ledger. Batch writes with `add-many` and `vote-many`. Read entries with few comments unless you are in a debate. Page long searches with `--limit` and `--offset`.
