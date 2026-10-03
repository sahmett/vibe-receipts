---
name: vibe-receipts
description: Measure how many hours were really spent on a git repo, from the gaps between the user's own prompts in Claude Code session logs (~/.claude/projects), with commits as context, and produce a visual HTML report. Use when the user asks how long they worked on a project, how many hours a repo / feature / week took, wants a timesheet or work-hours report for a client or invoice, or says "receipts", "kaç saat çalıştım", "çalışma süresi", "efor analizi".
---

# vibe-receipts

Measures working time on a git repo from the user's own prompts in Claude Code session logs
(`~/.claude/projects/<encoded-repo-path>/*.jsonl`):

- **Prompts** = messages the user typed + answers to `AskUserQuestion`. Claude replies, tool results,
  subagent traffic, compaction summaries and system/IDE injections are excluded.
- **Working time** = sum of gaps between consecutive prompts that are ≤ 15 min (longer = break).
- The report also shows the user's rhythm (median / P75 / P90 gap) and their personal threshold
  by Tukey's rule (Q3 + 1.5·IQR), plus a threshold-sensitivity table.
- Commits only add context: lines of code, lines/hour, minutes/commit, a daily commit log.
- With no session logs, it falls back to a rough commit-gap estimate (clearly labelled).

## Run it

The script lives next to this file: `scripts/receipts.py` (Python 3 stdlib only).

```bash
python3 <this-skill-dir>/scripts/receipts.py <repo-path> [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--author PATTERN] [--idle MIN|auto] [--lang en|tr]
```

- `<repo-path>`: default to the current working directory if the user did not name a repo.
- Turn the user's wording into flags: "this week" / "last month" / "in June" → `--since/--until`;
  "just my commits" → `--author "<git user.name>"` (read it with `git -C <repo> config user.name`).
- Reports go to `~/vibe-receipts/` (`<repo>-report.html` + `<repo>-daily.csv`). Never write them
  inside the analysed repo, and never commit them anywhere — they are personal work data.
- `--lang tr` when the user writes in Turkish, otherwise `--lang en`.
- `--idle auto` uses the user's own Tukey threshold instead of 15 min. Offer it when their threshold
  (printed on the `Rhythm` line) is far from 15, e.g. long autonomous Claude runs between prompts.
- If the same repo lives in two folders (two clones, or a moved folder), pass every matching
  `~/.claude/projects/...` folder with repeated `--transcripts`.

## Report back

After running, read the printed summary and the CSV, then answer in the user's language:

- **The headline number first:** working time from prompts (or say clearly it is the commit
  fallback when there were no session logs).
- Range, prompt and commit counts, and their rhythm: median gap and personal threshold. If the
  threshold is far from 15 min, mention how much `--idle auto` would change the total.
- The busiest days (from the CSV), and a short summary of what was done per day based on the
  commit subjects (`git -C <repo> log --since ... --until ... --pretty='%ad %s' --date=short`).
- The path to the HTML report, and open it if the environment can show files.

## Caveats to mention when relevant

- **Claude Code deletes transcripts after 30 days by default.** If the range is older and the
  transcript number looks too low, say so; the fix for the future is
  `"cleanupPeriodDays": 36500` in `~/.claude/settings.json` (suggest it, don't change it unasked).
- Work done outside Claude Code (manual edits, meetings, reading) is not in the transcript number.
- Bulk-copied static files can distort line counts and the fallback estimate; extend `VENDOR_RE` in `scripts/receipts.py` if a
  project has its own vendored folders.
