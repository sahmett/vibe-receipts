---
name: vibe-receipts
description: Estimate how many hours were really spent on a git repo, from its commit history and the Claude Code session transcripts in ~/.claude/projects, and produce a visual HTML report. Use when the user asks how long they worked on a project, how many hours a repo / feature / week took, wants a timesheet or work-hours report for a client or invoice, or says "receipts", "kaç saat çalıştım", "çalışma süresi", "efor analizi".
---

# vibe-receipts

Two independent measurements of working time on a git repo:

1. **Estimate (commit model).** Sum of gaps between consecutive commits (gaps > 150 min are breaks
   and dropped), scaled by an *effort ratio* derived from how much real code was added
   (docs, lockfiles, migrations and copied/vendor files weigh 0). Works on any repo.
2. **Ground truth (Claude transcripts).** Every event timestamp in
   `~/.claude/projects/<encoded-repo-path>/*.jsonl`; gaps ≤ 15 min count as active time.
   Only covers work done through Claude Code in that folder.

## Run it

The script lives next to this file: `scripts/receipts.py` (Python 3 stdlib only).

```bash
python3 <this-skill-dir>/scripts/receipts.py <repo-path> [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--author PATTERN] [--calibrate]
```

- `<repo-path>`: default to the current working directory if the user did not name a repo.
- Turn the user's wording into flags: "this week" / "last month" / "in June" → `--since/--until`;
  "just my commits" → `--author "<git user.name>"` (read it with `git -C <repo> config user.name`).
- Reports go to `~/vibe-receipts/` (`<repo>-rapor.html` + `<repo>-gunluk.csv`). Never write them
  inside the analysed repo, and never commit them anywhere — they are personal work data.
- `--calibrate` fits the minutes-per-line constant to the transcript total; offer it when both
  sources exist and the user wants the estimate tuned to their pace.

## Report back

After running, read the printed summary and the CSV, then answer in the user's language:

- **The headline number first.** Transcript active time if there are transcripts, otherwise the
  commit estimate, and say which one it is.
- Range, commit count, and how far the two methods differ.
- The busiest days (from the CSV), and a short summary of what was done per day based on the
  commit subjects (`git -C <repo> log --since ... --until ... --pretty='%ad %s' --date=short`).
- The path to the HTML report, and open it if the environment can show files.

## Caveats to mention when relevant

- **Claude Code deletes transcripts after 30 days by default.** If the range is older and the
  transcript number looks too low, say so; the fix for the future is
  `"cleanupPeriodDays": 36500` in `~/.claude/settings.json` (suggest it, don't change it unasked).
- Work done outside Claude Code (manual edits, meetings, reading) is not in the transcript number.
- Bulk-copied static files can distort the commit estimate; extend `VENDOR_RE` in the script if a
  project has its own vendored folders.
