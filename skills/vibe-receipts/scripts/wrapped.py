"""A year of archived receipts as a story, for receipts.py --wrapped: <out>/wrapped-<year>.html (tap-through cards,
Turkish and English) and <out>/wrapped-<year>.png (its last card, 1080 x 1920, to post).

Receipts archived since --wrapped existed carry their minutes and prompts per day, a weekday x hour prompt clock,
tokens and the model mix. Older ones only have their receipt lines (a day, week, month or quarter each): their
time is spread over those dates, so the months are right but they add no busiest day, streak or clock."""
import datetime, glob, json, os, re

def _year_of(md, r):
    """The year of a "MM-DD" line on receipt r: the start's, unless the range wraps into the next year."""
    y0, y1 = int(r['start'][:4]), int(r['end'][:4])
    return y0 if y0 == y1 or md >= r['start'][5:] else y1

def day_minutes(r):
    """{date: minutes} for receipt r, and whether it is exact (per day) or spread from its lines."""
    if isinstance(r.get('days'), dict) and r['days']: return {d: int(m) for d, m in r['days'].items()}, True
    out, exact = {}, True
    for _, label, m in r.get('items', []):
        label = str(label); m = int(m)
        if (x := re.search(r'(\d{4})-(\d{2})$', label)):                      # a month: 2026-10
            out[f'{x[1]}-{x[2]}-01'] = out.get(f'{x[1]}-{x[2]}-01', 0) + m; exact = False
        elif (x := re.search(r'(\d{4}) \D+(\d)$', label)):                    # a quarter: 2026 Q3 / 2026 Ç3
            for k in range(3):
                d = f'{x[1]}-{(int(x[2]) - 1) * 3 + k + 1:02d}-01'; out[d] = out.get(d, 0) + m / 3
            exact = False
        elif (x := re.search(r'(\d{2})-(\d{2})$', label)):                    # a day, or a week's Monday
            md = f'{x[1]}-{x[2]}'; d = f'{_year_of(md, r)}-{md}'; out[d] = out.get(d, 0) + m
            if re.search(r'(wk of|hafta)', label): exact = False
        elif (x := re.fullmatch(r'.*?(\d{4})', label)):                         # a year
            for k in range(12): d = f'{x[1]}-{k + 1:02d}-01'; out[d] = out.get(d, 0) + m / 12
            exact = False
    return out, exact

def _num(s):
    x = re.match(r'([\d.]+)\s*([KMB]?)', str(s).strip().replace(',', '.'))
    return float(x[1]) * {'': 1, 'K': 1e3, 'M': 1e6, 'B': 1e9}[x[2]] if x else 0

def _stat(r, *labels):
    """The value of a receipt's stats line by its label (TOKENS / TOKEN, MODEL), or ''."""
    return next((str(s[1]) for s in r.get('stats') or [] if isinstance(s, list) and len(s) > 1 and str(s[0]) in labels), '')

def year_stats(recs, year):
    Y = str(year); lo, hi = f'{Y}-01-01', f'{Y}-12-31'
    recs = [r for r in recs if r.get('start', '') <= hi and r.get('end', '') >= lo]
    months, exact_days, projects, prompts_day = [0.0] * 12, {}, {}, {}
    total = prompts = commits = 0; value = 0.0; approx = False
    clock = [[0] * 24 for _ in range(7)]; read = wrote = 0; mixes = []; thrs = []; longest = None
    for r in recs:
        dm, exact = day_minutes(r); approx |= not exact
        mins = sum(m for d, m in dm.items() if lo <= d <= hi)
        for d, m in dm.items():
            if lo <= d <= hi:
                months[int(d[5:7]) - 1] += m
                if exact and m: exact_days[d] = exact_days.get(d, 0) + m
        total += mins; projects[r['name']] = projects.get(r['name'], 0) + mins
        if isinstance(r.get('dprompts'), dict):
            for d, n in r['dprompts'].items():
                if lo <= d <= hi: prompts += n; prompts_day[d] = prompts_day.get(d, 0) + n
        elif not r.get('estimate'): prompts += int(r.get('prompts') or 0)
        commits += int(r.get('commits') or 0)
        if lo <= r.get('end', '') <= hi: value += float(r.get('value') or 0)
        if isinstance(r.get('clock'), list) and len(r['clock']) == 7:
            for i in range(7):
                for h in range(24): clock[i][h] += int(r['clock'][i][h])
        tok = r.get('tokens')
        if not (isinstance(tok, list) and len(tok) == 2):   # an older receipt: read its TOKENS line, "512M READ · 4.1M WRITTEN"
            parts = _stat(r, 'TOKENS', 'TOKEN').split('·'); tok = [_num(parts[0]), _num(parts[1])] if len(parts) == 2 else [0, 0]
        read += tok[0]; wrote += tok[1]
        mix = r.get('models')
        if not isinstance(mix, list):
            mix = [[f.lower(), int(p)] for f, p in re.findall(r'([A-Z]+) (\d+)%', _stat(r, 'MODEL'))]
        mixes.append((mix, tok[1], mins))
        try: thrs.append(float(str((r.get('thr') or ['', ''])[1]).split()[0].replace(',', '.')))
        except (ValueError, IndexError): pass
        if not longest or mins > longest[1]: longest = (r['name'], mins)
    days = sorted(exact_days)
    streak = best = 0; prev = None
    for d in days:
        x = datetime.date.fromisoformat(d)
        streak = streak + 1 if prev and (x - prev).days == 1 else 1; best = max(best, streak); prev = x
    busiest = max(exact_days.items(), key=lambda kv: kv[1]) if exact_days else None
    clicks = sum(map(sum, clock))
    peak = max(((i, h) for i in range(7) for h in range(24)), key=lambda ih: clock[ih[0]][ih[1]]) if clicks else None
    night = sum(clock[i][h] for i in range(7) for h in (22, 23, 0, 1, 2, 3)) / clicks if clicks else 0
    weekend = sum(map(sum, clock[5:])) / clicks if clicks else 0
    # the model mix, weighted by what each receipt's Claude wrote; by minutes if some receipt has no token count
    by_tok = all(w for m, w, _ in mixes if m); models = {}
    for mix, w, mins in mixes:
        for f, pc in mix: models[f] = models.get(f, 0) + pc * (w if by_tok else mins)
    msum = sum(models.values())
    mix = [m for m in sorted(((f, round(v / msum * 100)) for f, v in models.items()), key=lambda x: -x[1])[:3] if m[1] > 0] if msum else []
    hours_of_day = [sum(clock[i][h] for i in range(7)) for h in range(24)]
    peak_hour = max(range(24), key=lambda h: hours_of_day[h]) if clicks else None
    kind = None
    if clicks:
        kind = 'owl' if peak_hour >= 21 or peak_hour <= 3 else 'bird' if 5 <= peak_hour <= 9 else 'weekend' if weekend >= .35 else 'office'
    return dict(year=year, total=round(total), prompts=prompts, commits=commits, value=round(value, 2), approx=approx,
                projects=sorted(([n, round(m)] for n, m in projects.items() if round(m)), key=lambda x: -x[1]),
                months=[round(m) for m in months], activeDays=len(days), streak=best,
                busiest=dict(date=busiest[0], min=round(busiest[1]), prompts=prompts_day.get(busiest[0], 0)) if busiest else None,
                clock=clock if clicks else None, peakHour=peak_hour, peakDay=peak[0] if peak else None,
                night=round(night * 100), weekend=round(weekend * 100), read=read, written=wrote, mix=mix,
                breakAt=round(sum(thrs) / len(thrs), 1) if thrs else None, longest=longest, kind=kind, receipts=len(recs))

def build_wrapped(out, year, lang, render_png=None):
    """Returns (html path, png path or None, stats). Raises SystemExit when the year has no receipts."""
    recs = []
    for p in glob.glob(os.path.join(out, 'archive', '*.json')):
        try: recs.append(json.load(open(p, encoding='utf-8')))
        except (OSError, ValueError): continue
    W = year_stats(recs, year)
    if not W['receipts'] or not W['total']:
        raise SystemExit(f'Arşivde {year} için fiş yok.' if lang == 'tr' else f'No receipts archived for {year}.')
    tpl = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wrapped_template.html'), encoding='utf-8').read()
    data = json.dumps(W, ensure_ascii=False).replace('</', '<\\/')
    page = lambda poster: tpl.replace('__DATA__', data).replace('__LANG__', lang).replace('__POSTER__', 'true' if poster else 'false')
    dst = os.path.join(out, f'wrapped-{year}.html')
    with open(dst, 'w', encoding='utf-8') as f: f.write(page(False))
    png = None
    if render_png:   # the last card on its own, full bleed, for a story post
        tmp = os.path.join(out, f'.wrapped-{year}-poster.html')
        with open(tmp, 'w', encoding='utf-8') as f: f.write(page(True))
        try:
            if render_png(tmp, os.path.join(out, f'wrapped-{year}.png'), 540, 960, scale=2): png = os.path.join(out, f'wrapped-{year}.png')
        finally: os.remove(tmp)
    return dst, png, W
