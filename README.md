# 🧾 vibe-receipts

> **Receipts for your vibe coding.** How many hours did you *really* work with Claude?
> Your commits estimate it. Your session logs prove it.

![vibe-receipts demo report](docs/demo.jpg)

<sub>Demo built from 100% synthetic data with [`demo/make_demo.py`](demo/make_demo.py) · [full report](docs/demo-full.jpg)</sub>

One Python file, zero dependencies. Point it at a git repo and get a dark-mode HTML receipt
of the hours that went into it, checked two independent ways.

## Install as a Claude Code plugin (recommended)

```
/plugin marketplace add sahmett/vibe-receipts
/plugin install vibe-receipts@vibe-receipts
```

Then just ask Claude:

- *"How many hours did I work on this repo this week?"*
- *"Give me the receipts for June."*
- *"Make a timesheet of my commits for the client invoice."*

The skill turns your question into the right date range and author filter, runs the script,
and tells you the headline number, the busiest days, and what got done each day.

## Or run it directly

```bash
git clone https://github.com/sahmett/vibe-receipts
python3 vibe-receipts/receipts.py ~/code/my-project
```

You get `~/vibe-receipts/<repo>-report.html` and `<repo>-daily.csv`.
Reports are personal work data, so they are never written into the analysed repo.

## How it works

Two independent measurements, side by side:

### 1. Ground truth: Claude Code session logs
Claude Code keeps a log of every session in `~/.claude/projects/<project>/*.jsonl`.
Every event has a timestamp. Gaps of **≤ 15 min** between events count as active time;
anything longer means you walked away and is dropped.

- The log folder is found automatically from the repo path, including sessions in
  `.claude/worktrees/`. Use `--transcripts <dir>` to point somewhere else.
- Only sessions opened in that repo count. Work done outside Claude Code (manual edits,
  meetings, reading) is not in this number.

### 2. Estimate: the commit "effort ratio" model
Works on any repo, even without session logs.

```
TOTAL        = Measured × Effort ratio
Effort ratio = 1 + (effective added code × CODE_RATE) / Measured
```

1. **Clean up:** merge and stash commits are dropped.
2. **Measured:** sum of the gaps between consecutive commits. A gap over **150 min** is a
   break (sleep, lunch, life) and is dropped; every shorter gap counts in full.
3. **Effective added code:** added lines weighted by type:
   `code ×1.0 · config ×0.4 · docs ×0 · copied/vendor ×0 · generated (lockfiles, migrations) ×0`.
   Bulk-copied files (`vendor/`, `prototypes/`, `_archive/`) would wreck the estimate, so they
   are excluded. Extend `VENDOR_RE` for your own project.
4. **Effort ratio:** one coefficient derived purely from code density. No made-up
   "add 20 %" fudge factor.

### Calibrate it to your pace

`CODE_RATE` (minutes per effective added line) depends on how you work. If a repo has
session logs, fit it to the real number:

```bash
python3 receipts.py ~/code/my-project --since 2026-06-01 --until 2026-06-30 --calibrate
```

Write the printed value into `CODE_RATE` at the top of the script. The totals will then match
by design. The real test of the model is the **per-day distribution**.

> ⚠️ **Claude Code deletes session logs after 30 days by default.**
> To keep your receipts, add `"cleanupPeriodDays": 36500` to `~/.claude/settings.json`.
> For days whose logs are gone, only the commit estimate is left.

## Options

| Flag | Meaning |
|---|---|
| `repo` | git repo to analyse (default `.`) |
| `--since / --until` | day range `YYYY-MM-DD`, applied to both commits and logs |
| `--author` | only this author's commits (`git log --author` pattern) |
| `--transcripts DIR` | Claude log folder, overrides auto-detection (repeatable) |
| `--calibrate` | fit `CODE_RATE` to the session-log total |
| `--lang en\|tr` | report language (default: from `$LANG`, else English) |
| `--name` | project name shown in the report |
| `--out DIR` | output folder (default `~/vibe-receipts`) |

Constants at the top of `receipts.py`:

| Constant | Default | Meaning |
|---|---|---|
| `BREAK` | 150 min | gap between commits that counts as a break |
| `CODE_RATE` | 0.02 min/line | how much each effective added line adds to the estimate |
| `TR_IDLE` | 15 min | idle threshold for session logs |
| `CODE_W` | code 1.0 / config 0.4 / docs 0 | weights for added lines |
| `VENDOR_RE`, `GEN_RE` | regex | copied/vendor and generated file patterns to exclude |

## Export as an image

```bash
bash to_jpg.sh ~/vibe-receipts/<repo>-report.html   # macOS + Google Chrome + Pillow
```

## Repo layout

```
.claude-plugin/            plugin + marketplace manifests
skills/vibe-receipts/
├── SKILL.md               when and how Claude runs it
└── scripts/
    ├── receipts.py        analysis + HTML report
    └── to_jpg.sh          report → JPEG
receipts.py, to_jpg.sh     shortcuts (symlinks)
demo/make_demo.py          rebuilds the synthetic demo above
```
