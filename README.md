# Ledger
A generic ledger designed for agentic development. Each entry contains a description defining the item in the list, the list of dependencies to other ledger entries as well as the description of the entry, and a voting track record so multiple agents can independently vote on the entry and provide a justification for their assessment, and come to a consensus or delegate the decision back to the user. 

The graph provides the necessary context for a given issue and allows mapping the complete dependency chain. 

## Files

| File | What |
| --- | --- |
| `ledger_api.py` | The ledger API: the only code that touches the database. Every client below goes through it. |
| `ledger.py` | Command line over the API |
| `ledger_mcp.py` | MCP server over the API for agents (`--author NAME`; the author is fixed per server, no delete or edit-others operations) |
| `ledger_viz.py`, `viewer.html` | Visualization: live force-directed graph, sortable table, disputes view, activity feed; refreshes about once a second while the ledger changes |

## Quick start

```
python ledger.py add --kind requirement --title "Single-file store" --body "One file, safe for several writers" --author me
python ledger.py add --kind decision --title "Use SQLite" --author me --ref "L-0001:implements"
python ledger.py vote L-0002 up --author me --reason "Fits the single-file requirement"
python ledger.py list
python ledger_viz.py serve            # http://127.0.0.1:8765
```

Entry ids look like `L-0001`. Text arguments accept `@path` to read from a file. The first entry has nothing to reference yet; later entries through the MCP server must carry at least one reference.

## Commands

`add`, `update`, `show`, `list`, `dump`, `comment`, `vote`, `link`, `unlink`, `merge`, `similar` (candidate duplicates), `disagreements` (split votes), `queue VOTER` (entries a voter has not voted on or that changed since their vote), `check`, `export` (Markdown), `backup` (consistent copy of the database). Administrative commands (`delete-entry`, `edit-comment`, `delete-comment`, `edit-vote-reason`) are limited to the authors `main` and `user`.

## Rules the tool enforces

- One vote per voter per entry; a vote needs a reason, and re-voting replaces the old vote (the reason is kept as a comment).
- Changes to an entry are logged as comments with the reason.
- A reference needs a comment describing the relationship; entries cannot reference themselves.
- Merging moves comments and references to the surviving entry and redirects links.

## Skill

`.claude/skills/ledger/SKILL.md` is a Claude Code skill that teaches an agent to use the ledger: how to write entries, vote, debate, find and merge duplicates, and propagate changes. Opened in this repository, Claude Code picks it up as a project skill. To use it elsewhere, copy the folder to `~/.claude/skills/ledger/` (and use absolute paths to `ledger.py`).

## License

MIT, see `LICENSE`.

## Agents

`python ledger_mcp.py --author alpha` serves the API over MCP (stdio). Example `.mcp.json` entry:

```json
{ "mcpServers": { "ledger-alpha": { "command": "python", "args": ["ledger_mcp.py", "--author", "alpha"] } } }
```
