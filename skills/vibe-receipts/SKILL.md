---
name: vibe-receipts
description: Measure how many hours were really spent on a project folder (git repo or not), from the gaps between the user's own prompts in Claude Code session logs (~/.claude/projects), with commits as context, and produce a visual HTML report. Use when the user asks how long they worked on a project, how many hours a repo / feature / week took, wants a timesheet or work-hours report for a client or invoice, or says "receipts", "kaç saat çalıştım", "çalışma süresi", "efor analizi".
---

# vibe-receipts

Measures working time on a project folder from the user's own prompts in Claude Code session logs
(`~/.claude/projects/<encoded-repo-path>/*.jsonl`):

- **Prompts** = messages the user typed + answers to `AskUserQuestion`. Claude replies, tool results,
  subagent traffic, compaction summaries and system/IDE injections are excluded.
- **Working time** = sum of gaps between consecutive prompts that are ≤ the break threshold
  (longer = break).
- **Break threshold** is computed automatically from the user's own gaps with Tukey's rule:
  `Q3 + 1.5 × IQR` (Q1/Q3 = 25th/75th percentile of the gaps, IQR = Q3 − Q1). With fewer than
  20 gaps it falls back to 15 min. It never goes above 30 min (the line then says "capped at 30 min";
  tell the user what their rhythm gave and that the cap applied). The user can override it with `--break MIN`.
- The report shows the rhythm (Q1 / median / Q3 / P90), the threshold used and why, and a
  threshold-sensitivity table.
- Commits only add context: lines of code, lines/hour, minutes/commit, a daily commit log.
  Git is optional: with no repo, no commits in range or no git installed, the `Commits` line says
  why and the hours are unaffected. Pass that reason on to the user in one sentence; the tool never
  connects to GitHub, it only reads local git history.
- With no session logs, it falls back to a rough commit-gap estimate (clearly labelled).

## Run it

The script lives next to this file: `scripts/receipts.py` (Python 3 stdlib only).

```bash
python3 <this-skill-dir>/scripts/receipts.py <repo-path> [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--author PATTERN] [--break MIN] [--lang en|tr]
```

- `<repo-path>`: default to the current working directory if the user did not name a folder.
- Turn the user's wording into flags: "this week" / "last month" / "in June" → `--since/--until`;
  "just my commits" → `--author "<git user.name>"` (read it with `git -C <repo> config user.name`).
- Reports go to `~/vibe-receipts/` (`<repo>-report.html` + `<repo>-daily.csv` + `<repo>-receipt.png`,
  a shareable receipt card rendered with a local headless Chrome; skipped with a note if none is found). Never write them
  inside the analysed repo, and never commit them anywhere — they are personal work data.
- `--lang tr` when the user writes in Turkish, otherwise `--lang en`.
- `--built "<what it is>"`: 1–3 words saying what the project is, for the `BUILT` line on the receipt
  (e.g. "e-commerce site", "mobile app", "CLI tool", "admin panel"). Infer it from the repo's README and
  manifest (`package.json`, `pyproject.toml`, …), in the report language. If you can't tell, leave it out.
- Leave `--break` out by default (automatic threshold). Pass `--break MIN` only when the user asks for
  a specific threshold ("recalculate with 20 minutes", "15 dk ile hesapla"); re-run and compare.
- If the same repo lives in two folders (two clones, or a moved folder), pass every matching
  `~/.claude/projects/...` folder with repeated `--transcripts`.

## Report back

After running, read the printed summary and the CSV, then answer in the user's language:

- **The headline number first:** working time from prompts (or say clearly it is the commit
  fallback when there were no session logs).
- **The break threshold, always.** Read the `Break threshold` / `Mola sınırı` line: say the value and
  how it was set (computed from their rhythm / set by them / default because too few prompts).
  Explain it in one plain sentence from the `Rhythm` line, e.g. "half of your gaps are between
  Q1 and Q3 min; a gap longer than Q3 + 1.5 × that range is unusual for you, so it counts as a break".
- Show 2–3 alternatives from the `Sensitivity` line (e.g. 10 / 15 / 30 min) and offer to recompute
  with any threshold they choose.
- Range, prompt and commit counts.
- Tokens from the `Tokens` line: read (the context Claude processed, mostly cache reads of the same
  conversation) vs written (what Claude actually produced). Subagent usage is included.
- Agents from the `Agents` line: main Claude Code sessions (runs) and the subagents Claude started.
- Model mix from the `Model mix` line: which model families wrote the work (share of output tokens).
- Token value from the `Token value` line: what these tokens would cost at Anthropic API list prices
  (the `TOKEN VALUE` line on the receipt), which part is the biggest (usually cache reads), and the
  "without cache" number. Say it is not what a subscription costs them. If the user asks for another
  currency, convert it with a current exchange rate. A `≥` or "unpriced" note means some models are
  missing from `PRICES` in `scripts/receipts.py`.
- The busiest days (from the CSV), and a short summary of what was done per day based on the
  commit subjects (`git -C <repo> log --since ... --until ... --pretty='%ad %s' --date=short`).
- The path to the HTML report and the receipt PNG, and open them if the environment can show files.
- The `Share:` line, as-is in a code block, as a ready-to-post caption for the receipt PNG. Never post it
  anywhere yourself. If the project name is private, offer to re-run with `--name` to hide it.

## Name things twice: plain words + the math term

Whenever you mention a statistic, give the everyday meaning and its mathematical name together, in
the user's language, e.g.:

| Plain | Math term (EN) | Math term (TR) |
|---|---|---|
| typical gap | median, P50 | medyan / ortanca, P50 |
| short gaps / long gaps | 1st / 3rd quartile, Q1 = P25 / Q3 = P75 | 1. / 3. çeyrek |
| normal pace (middle half of gaps) | interquartile range, IQR = Q3 − Q1 | çeyrekler arası aralık |
| rare long gaps | 90th percentile, P90 | 90. yüzdelik |
| break threshold | Tukey upper fence, Q3 + 1.5·IQR | Tukey üst çiti |
| a break | outlier | aykırı değer |
| share of gaps under a threshold | cumulative distribution (CDF) | kümülatif dağılım |

## Caveats to mention when relevant

- **Claude Code deletes transcripts after 30 days by default.** If the range is older and the
  transcript number looks too low, say so; the fix for the future is
  `"cleanupPeriodDays": 36500` in `~/.claude/settings.json` (suggest it, don't change it unasked).
- Work done outside Claude Code (manual edits, meetings, reading) is not in the transcript number.
- Bulk-copied static files can distort line counts and the fallback estimate; extend `VENDOR_RE` in `scripts/receipts.py` if a
  project has its own vendored folders.
