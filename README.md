# Ledger
A generic ledger designed for agentic development. Each entry contains a description defining the item in the list, the list of dependencies to other ledger entries as well as the description of the entry, and a voting track record so multiple agents can independently vote on the entry and provide a justification for their assessment, and come to a consensus or delegate the decision back to the user. 

The graph provides the necessary context for a given issue and allows mapping the complete dependency chain. 

## Files

| File | What |
| --- | --- |
| `ledger_api.py` | The ledger API: the only code that touches the database. Every client below goes through it. |
| `ledger.py` | Command line over the API |
| `ledger_viz.py`, `viewer.html` | Visualization: live force-directed graph, sortable table, disputes view, activity feed; refreshes about once a second while the ledger changes |
| `components.html` | Component map generated from the ledger (boxes = component entries, rows = members, arrows = member-anchored references; automatic layout; side bar with assumptions, gaps and open issues), served at `/components` |

## Quick start

```
python ledger.py add --kind requirement --title "Single-file store" --body "One file, safe for several writers" --author me
python ledger.py add --kind decision --title "Use SQLite" --author me --ref "L-0001:implements"
python ledger.py vote L-0002 up --author me --reason "Fits the single-file requirement"
python ledger.py list
python ledger_viz.py serve            # http://127.0.0.1:8765
```

Entry ids look like `L-0001`. Text arguments accept `@path` to read from a file. The first entry has nothing to reference yet; every later entry should reference at least one other.

## Commands

`add` (reports possible duplicates), `add-many` (JSON batch, all or nothing), `set` (create or update), `update`, `get`/`show`, `find`/`list` (searches comments and vote reasons too; `--limit`/`--offset` paging), `dump`, `comment`, `vote`, `vote-many` (JSON batch), `link`, `unlink`, `merge`, `similar` (candidate duplicates), `disagreements` (split votes), `queue VOTER` (ids a voter has not voted on or that changed since their vote), `review VOTER` (the same entries in full), `affected` (entries with their linked neighbours), `check`, `export` (Markdown), `backup` (consistent copy of the database).

Component map: `component` / `components-many` (make an entry a box), `member` / `members-many` / `member-rm` (its rows: APIs, events emitted, events subscribed), `link --from-member --to-member --basis` / `links-many` (calls), `map` (the generated model as JSON).

`--author` can appear anywhere and defaults to `LEDGER_AUTHOR`. Text arguments accept `@file` or `@-` (stdin); batch commands read JSON from a file or `-` (stdin). Administrative commands (`delete-entry`, `edit-comment`, `delete-comment`, `edit-vote-reason`) are limited to the authors `main` and `user`.

## Rules the tool enforces

- One vote per voter per entry; a vote needs a reason, and re-voting replaces the old vote (the reason is kept as a comment).
- Changes to an entry are logged as comments with the reason.
- A reference needs a comment describing the relationship; entries cannot reference themselves.
- Merging moves comments and references to the surviving entry and redirects links.
- Only an entry's author may edit it; entries that record a decision by `user` (authored or edited by `user`) can only be edited by `user` or `main`. Others comment instead.

## Skill

`.claude/skills/ledger/SKILL.md` is a Claude Code skill that teaches an agent to use the ledger: how to write entries, vote, debate, find and merge duplicates, and propagate changes. Opened in this repository, Claude Code picks it up as a project skill. To use it elsewhere, copy the folder to `~/.claude/skills/ledger/` (and use absolute paths to `ledger.py`).

## License

MIT, see `LICENSE`.

## Agents

Agents use the ledger through the skill and the command line only; no server is needed, so nothing is added to an agent's context until it loads the skill. Give each agent its own name with `LEDGER_AUTHOR`, and tell it to load the `ledger` skill.
