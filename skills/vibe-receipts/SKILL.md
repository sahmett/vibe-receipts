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
- With no session logs, it estimates the hours from commit sessions (about 48 min per session of
  commits less than 60 min apart; ~15% average error on Claude-assisted solo repos), clearly labelled.

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
- `--video` when the user wants a video, a reel/TikTok/Short or "something to post" ("video yap", "paylaşmak
  için video"): it also writes `<repo>-receipt.mp4`, the receipt printing out of a thermal printer (1080×1920,
  with sound). It records in real time, so the run takes ~15 s longer; leave it out otherwise.
- `--board` when the user wants to see their receipts together ("all my receipts", "fişlerim", "pano", a
  timesheet across projects): every run archives its receipt in `~/vibe-receipts/archive/`, and `--board`
  rebuilds `~/vibe-receipts/board.html` from all of them. With no repo (`receipts.py --board`) it only rebuilds.
  For client work pass `--client "<name>"` (the card goes to "to bill"), and `--status paid` once it is invoiced.
- `--invoice "<client>"` with no repo when the user wants to bill a client or needs a timesheet ("fatura çıkar",
  "Northwind'e fatura", "timesheet"): it takes that client's archived receipts still "to bill" and writes an
  HTML and PDF page to `~/vibe-receipts/invoices/`. Add `--rate <hourly>` for an invoice (without it, hours
  only), `--currency`, `--tax <percent>` for VAT/KDV, `--bill-from "Name\nAddress"` and `--bill-to`, and
  `--since`/`--until` for a month. Ask for the rate and currency if the user did not give them; never guess a
  rate. Pass `--mark-billed --board` only when the user says the invoice is sent or final.
- `--wrapped [YEAR]` with no repo for a year in review ("yılım nasıl geçti", "Wrapped", "year in review"): it writes
  `~/vibe-receipts/wrapped-<year>.html` (a story to tap through) and `wrapped-<year>.png` (1080×1920, to post).
  Open both. Its numbers come only from archived receipts, so if the user has projects they never ran
  receipts.py on, offer to run it on them first (each run archives its receipt).
- `--share` when the user wants to post a receipt as a link ("paylaşmak için link", "share a link"): it prints a
  `Share link:` whose preview card shows the receipt. The site reads the receipt from the link to draw the card
  and stores nothing; the client is left out, but the project name is in it, so offer `--name` if it is private.
  `--link` instead keeps the receipt in the `#` part, which no server sees, but its preview is the site's card:
  use it when the user does not want the numbers to reach any server.
- Leave `--break` out by default (automatic threshold). Pass `--break MIN` only when the user asks for
  a specific threshold ("recalculate with 20 minutes", "15 dk ile hesapla"); re-run and compare.
- If the same repo lives in two folders (two clones, or a moved folder), pass every matching
  `~/.claude/projects/...` folder with repeated `--transcripts`.

## When the user wants to share the receipt

"Fişi paylaş", "paylaşmak istiyorum", "share my receipt", "post this", "make it go viral": they want something
ready to post, not a report.

1. Run with `--share` (the link previews as the receipt) and `--video` (the clip for Reels, TikTok and Shorts).
   If the receipt was already made for this range, still re-run: it is quick and gives the kit the link.
2. Read `<out>/<name>-share.md`, the share kit the run printed as `Kit :`. Show the receipt PNG (open it), then
   every post from the kit in its own code block, under its platform name: X / Threads / Bluesky (three), LinkedIn,
   Reels / TikTok / Shorts. Then the kit's "before you post" tips, in a short list.
3. Ask which one they will use, and offer to tune it: shorter, funnier, more technical, in the other language,
   or with their own takeaways in the two `[ ]` lines of the LinkedIn post. Keep every number exactly as the kit
   has it; never round or inflate the hours, prompts or token value.
4. If the project name is private, offer `--name` to re-run under another name before they post.

Never post, send or schedule anything yourself, and never open the user's social accounts.

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
- The path to the HTML report and the receipt PNG (and the MP4 with `--video`, the board with `--board`), and
  open them if the environment can show files. Without `--video`, offer it once: a clip of the receipt printing out is made
  for posting.
- With `--share` or `--link`, the `Share link:` or `Link:` line as-is. Never post it anywhere yourself.
- The `Share:` line, as-is in a code block, as a ready-to-post caption for the receipt PNG or video. Never post it
  anywhere yourself. If the project name is private, offer to re-run with `--name` to hide it. Mention that
  `<name>-share.md` (the `Kit :` line) has a post per platform, and offer to show it.

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
