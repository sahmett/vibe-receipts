"""Six made-up receipts for the public site, in the archive format receipts.py writes, in Turkish and in English.
Every TOTAL is the sum of its lines. They are dated as if today were TODAY."""

TODAY = '2026-10-16'

LABELS = {
    'tr': dict(kind='ÇALIŞMA SÜRESİ FİŞİ', project='PROJE', built='YAPILAN', period='DÖNEM', active='AKTİF GÜN', qty='ADET',
               item='KALEM', time='SÜRE', value='TOKEN VALUE', total='TOPLAM', h='s', m='d'),
    'en': dict(kind='WORK TIME RECEIPT', project='PROJECT', built='BUILT', period='PERIOD', active='ACTIVE DAYS', qty='QTY',
               item='ITEM', time='TIME', value='TOKEN VALUE', total='TOTAL', h='h', m='m'),
}
WORDS = {
    'tr': dict(prompt='prompt', commit='commit', week='hafta', days='GÜN', day='GÜN', runs='OTURUM', subs='SUBAGENT', read='OKUNAN',
               written='YAZILAN', stats=('PROMPT', 'AGENT', 'TOKEN', 'MODEL', 'COMMIT', 'KOD SATIRI'), thr='MOLA SINIRI', minute='dk', dec=',',
               dow=['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz'],
               auto='Kendi prompt ritmine göre. Daha uzun aralıklar mola sayılır, çalışma değil.',
               few='Varsayılan: ritmini okumak için prompt az. Daha uzun aralıklar mola sayılır.',
               est=('OTURUM KAYDI YOK', 'Commit oturumlarından tahmin.'),
               built={'crm': 'crm paneli', 'ledger': 'muhasebe api', 'recipe': 'recipe app', 'mood': 'moodboard', 'cli': 'cli aracı', 'mobile': 'mobil uygulama'}),
    'en': dict(prompt='prompts', commit='commits', week='wk of', days='DAYS', day='DAY', runs='RUNS', subs='SUBAGENTS', read='READ',
               written='WRITTEN', stats=('PROMPTS', 'AGENTS', 'TOKENS', 'MODEL', 'COMMITS', 'CODE LINES'), thr='BREAK THRESHOLD', minute='min', dec='.',
               dow=['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
               auto='Based on your own prompt rhythm. Longer gaps are breaks, not work.',
               few='Default: too few prompts to read your rhythm. Longer gaps are breaks.',
               est=('NO SESSION LOGS', 'Estimated from your commit sessions.'),
               built={'crm': 'crm panel', 'ledger': 'ledger api', 'recipe': 'recipe app', 'mood': 'moodboard', 'cli': 'cli tool', 'mobile': 'mobile app'}),
}

# name, client, status, built, start, end, active days, lines [(qty, day or week, minutes)], weekly?, prompts?, agents, tokens, model, commits, code, value, threshold
RAW = [
    ('orbit-crm', 'Northwind', 'due', 'crm', '2026-10-01', '2026-10-12', 9, [(112, '09-28', 252), (241, '10-05', 631), (145, '10-12', 387)], True, True,
     (9, 6), ('512M', '4.1M'), 'OPUS 88% · SONNET 12%', 41, '+5,870', 264.20, ('14.8', 'auto')),
    ('tiny-ledger', 'Northwind', 'due', 'ledger', '2026-10-13', '2026-10-15', None, [(88, '10-13', 260), (79, '10-14', 235), (64, '10-15', 170)], False, True,
     (3, 1), ('240M', '1.9M'), 'SONNET 71% · OPUS 29%', 19, '+1,948', 122.40, ('15.0', 'few')),
    ('pixel-pantry', 'Acme', 'paid', 'recipe', '2026-09-14', '2026-09-17', None, [(73, '09-14', 226), (50, '09-15', 186), (47, '09-16', 171), (35, '09-17', 82)], False, True,
     (4, 0), ('273M', '2.29M'), 'OPUS 94% · SONNET 6%', 26, '+3,293', 138.14, ('13.3', 'auto')),
    ('moodboard-ai', 'Acme', 'paid', 'mood', '2026-08-02', '2026-08-02', None, [(64, '08-02', 198)], False, True,
     (1, 0), ('88M', '0.7M'), 'OPUS 100%', 7, '+812', 41.30, ('15.0', 'few')),
    ('invoice-cli', None, 'personal', 'cli', '2026-10-03', '2026-10-09', None,
     [(120, '10-03', 310), (96, '10-04', 242), (88, '10-05', 225), (101, '10-06', 270), (110, '10-07', 305), (97, '10-08', 258), (90, '10-09', 290)], False, True,
     (11, 3), ('731M', '5.6M'), 'OPUS 91% · HAIKU 9%', 58, '+4,402', 391.08, ('12.6', 'auto')),
    ('habit-loop', None, 'personal', 'mobile', '2026-09-21', '2026-09-23', None, [(12, '09-21', 130), (9, '09-22', 104), (15, '09-23', 158)], False, False,
     None, None, None, 36, '+2,104', None, None),
]


def receipts(lang):
    import datetime
    w, out = WORDS[lang], []
    for (name, client, status, built, start, end, active, lines, weekly, has_p, agents, tokens, model, commits, code, value, thr) in RAW:
        unit = w['prompt'] if has_p else w['commit']
        def label(md):
            if weekly: return f"{w['week']} {md}"
            d = datetime.date.fromisoformat(f'2026-{md}')
            return f"{w['dow'][d.weekday()]} {md}"
        days = (datetime.date.fromisoformat(end) - datetime.date.fromisoformat(start)).days + 1
        period = (start if start == end else f'{start} → {end[5:]}') + f" · {days} {w['day'] if days == 1 else w['days']}"
        st = w['stats']
        stats = ([[st[0], f'{sum(q for q, _, _ in lines):,}'], [st[1], f"{agents[0]} {w['runs']} · {agents[1]} {w['subs']}"],
                  [st[2], f"{tokens[0]} {w['read']} · {tokens[1]} {w['written']}"], [st[3], model], None] if has_p else []) + [[st[4], str(commits)], [st[5], code]]
        if thr: threshold = [w['thr'], f"{thr[0].replace('.', w['dec'])} {w['minute']}", w[thr[1]]]
        else: threshold = [w['est'][0], '', w['est'][1]]
        items = [[q, f'{unit} · {label(md)}', m] for q, md, m in lines]
        out.append(dict(key=f'{name}_{start}_{end}', name=name, built=w['built'][built], period=period, active=active, start=start, end=end,
                        items=items, min=sum(i[2] for i in items), prompts=sum(q for q, _, _ in lines) if has_p else 0, commits=commits,
                        estimate=not has_p, stats=stats, value=value, value_text=f'${value:,.2f}' if value else None, thr=threshold,
                        client=client, status=status, lang=lang, made=end + 'T20:00:00', L=LABELS[lang]))
    return sorted(out, key=lambda r: (r['end'], r['start']), reverse=True)
