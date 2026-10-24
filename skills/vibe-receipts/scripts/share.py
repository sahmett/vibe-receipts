"""The share kit: ready-to-post texts for one receipt, one per platform, filled in with its own numbers, for
receipts.py to write as <out>/<name>-share.md next to the receipt PNG (and the MP4 with --video).

Every post opens on the receipt's own joke (the quote it printed: "It's a 2-hour project.") or a number, says
how the time was measured, and ends on the link. LinkedIn leaves two lines for the user's own takeaways:
the one part only they can write."""
import datetime

W = {
 'en': dict(
    title='Share kit', assets='Attach', png='the receipt picture', mp4='the printing video', link='the link',
    x='X / Threads / Bluesky', li='LinkedIn', reel='Reels / TikTok / Shorts (with the video)',
    tips='Before you post',
    tip=['Upload the picture or the video itself; a post with only a link travels less far.',
         'On X and LinkedIn, put the link in the first reply instead of the post.',
         'Post when your people are online, and answer the first comments in the first hour.',
         'Fill in the two [ ] lines on LinkedIn yourself: that is the part people react to.'],
    t=lambda h, m: f'{h}h {m}m', days=lambda n: f'{n} day' + ('s' if n != 1 else ''),
    x1='{quote}\n\n{time} later. 🧾\n\n{link}',
    x2='Asked for the receipt on {name}.\n\n{prompts} · {days} · {time}{value_line}\n\n{measured}\n{link}',
    x3_tok='Claude read {read} tokens and wrote {written} so I could ship {name}.\nI typed {prompts}.\n\nTotal: {time}. 🧾\n{link}',
    x3_day='Longest day on {name}: {busy_time}, on a {busy_day}.\nWhole thing: {time} over {days}.\n\nMe, at the start: {quote} 🧾\n{link}',
    x3_plain='Me: {quote}\nThe receipt: {time}. 🧾\n\n{link}',
    li_post=('{quote} That is what I said about {name}. So I measured it.\n\n'
             '{what_cap} took {time} over {days}: {prompts} to Claude Code{value_part}.\n\n'
             '{how}\n\n'
             'What I took from it:\n• [what took longer than you thought]\n• [what the AI made fast]\n\n'
             'The receipt is below. You can get your own; it runs on your machine and uploads nothing: {link}\n\n'
             '#ClaudeCode #BuildInPublic #VibeCoding'),
    reel_post='{quote} → {time} 🧾 {prompts}, {days}. Receipts don\'t lie.\nGet yours: {site}\n#vibecoding #claudecode #buildinpublic #developer #vibereceipts',
    measured='Measured from the gaps between my own Claude Code prompts.', measured_est='Estimated from my commit sessions.',
    how='How it is measured: the gaps between my own prompts. A gap longer than {thr} counts as a break, not as work. No timer to forget, no guessing.',
    how_est='How it is measured: there were no Claude Code logs, so the time is estimated from my commit sessions. No timer to forget.',
    value_line='\n{value} worth of tokens', value_part=', about {value} of tokens at API prices',
    prompts=lambda n: f'{n:,} prompt' + ('s' if n != 1 else ''), commits=lambda n: f'{n:,} commit' + ('s' if n != 1 else ''),
    what=lambda name, built: built or name, what_cap=lambda name, built: f'{name} ({built})' if built else name),
 'tr': dict(
    title='Paylaşım kiti', assets='Ekle', png='fiş görseli', mp4='yazdırma videosu', link='link',
    x='X / Threads / Bluesky', li='LinkedIn', reel='Reels / TikTok / Shorts (videoyla)',
    tips='Paylaşmadan önce',
    tip=['Görseli ya da videoyu doğrudan yükle; yalnızca link olan gönderi daha az yayılır.',
         "X ve LinkedIn'de linki gönderiye değil ilk yoruma koy.",
         'Takipçilerin çevrimiçiyken paylaş, ilk saatteki yorumlara cevap ver.',
         "LinkedIn'deki iki [ ] satırını kendin doldur: insanların tepki verdiği kısım orası."],
    t=lambda h, m: f'{h} saat {m} dakika', days=lambda n: f'{n} gün',
    x1='{quote}\n\n{time} sonra. 🧾\n\n{link}',
    x2='{name} için fişi istedim.\n\n{prompts} · {days} · {time}{value_line}\n\n{measured}\n{link}',
    x3_tok='{what} çıksın diye Claude {read} token okudu, {written} token yazdı.\nBen {prompts} yazdım.\n\nToplam: {time}. 🧾\n{link}',
    x3_day='{name} üzerinde en uzun günüm: {busy_day}, {busy_time}.\nToplamı: {days} içinde {time}.\n\nBen {quote_short} demiştim. 🧾\n{link}',
    x3_plain='Ben: {quote_short}\nFiş: {time}. 🧾\n\n{link}',
    li_post=('{name} için {quote_short} demiştim. Ölçtüm.\n\n'
             '{what_cap} {days} içinde {time} sürdü: Claude Code\'a {prompts}{value_part}.\n\n'
             '{how}\n\n'
             'Bundan çıkardıklarım:\n• [düşündüğünden uzun süren şey]\n• [yapay zekânın hızlandırdığı şey]\n\n'
             'Fiş aşağıda. Sen de kendi fişini çıkarabilirsin; kendi bilgisayarında çalışıyor, hiçbir şey yüklemiyor: {link}\n\n'
             '#ClaudeCode #BuildInPublic #VibeCoding'),
    reel_post='{quote} → {time} 🧾 {prompts}, {days}. Fiş yalan söylemez.\nSen de çıkar: {site}\n#vibecoding #claudecode #buildinpublic #yazılım #vibereceipts',
    measured="Kendi Claude Code prompt'larım arasındaki aralıklardan ölçüldü.", measured_est='Commit oturumlarımdan tahmin edildi.',
    how="Nasıl ölçülüyor: kendi prompt'larım arasındaki aralıklardan. {thr} sınırından uzun bir aralık çalışma değil mola sayılıyor. Unutulan sayaç yok, tahmin yok.",
    how_est='Nasıl ölçülüyor: Claude Code kaydı yoktu, süre commit oturumlarımdan tahmin edildi. Unutulan sayaç yok.',
    value_line='\n{value} değerinde token', value_part=', API fiyatıyla yaklaşık {value} değerinde token',
    prompts=lambda n: f'{n:,} prompt'.replace(',', '.'), commits=lambda n: f'{n:,} commit'.replace(',', '.'),
    what=lambda name, built: built or name, what_cap=lambda name, built: f'{name} ({built})' if built else name),
}
DOW = {'en': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'],
       'tr': ['pazartesi', 'salı', 'çarşamba', 'perşembe', 'cuma', 'cumartesi', 'pazar']}

def _cap(s, lang):   # a sentence's first letter, in that language's case (Turkish i -> İ)
    if not s: return s
    first = {'i': 'İ', 'ı': 'I'}.get(s[0], s[0].upper()) if lang == 'tr' else s[0].upper()
    return first + s[1:]

def _short(n):
    for div, suf in ((1e9, 'B'), (1e6, 'M'), (1e3, 'K')):
        if n >= div:
            v = n / div; return (f'{v:.2f}' if v < 10 else f'{v:.1f}' if v < 100 else f'{v:.0f}').rstrip('0').rstrip('.') + suf
    return str(int(n))

def posts(rec, lang, quote, link, site):
    """[(platform, text)] for one archived receipt."""
    w = W[lang]; m = int(rec['min'])
    span = (datetime.date.fromisoformat(rec['end']) - datetime.date.fromisoformat(rec['start'])).days + 1
    days = w['days'](rec.get('active') or span)
    count = w['commits'](rec['commits']) if rec.get('estimate') else w['prompts'](rec['prompts'])
    quote_short = quote.strip('\u201c\u201d"').rstrip('.')
    quote_short = (f'\u201c{quote_short}.\u201d' if lang == 'en' else f'\u201c{quote_short}\u201d')
    value = rec.get('value_text')
    f = dict(quote=quote, quote_short=quote_short, time=w['t'](m // 60, m % 60), name=rec['name'], prompts=count, days=days,
             link=link, site=site, what=w['what'](rec['name'], rec.get('built')), what_cap=w['what_cap'](rec['name'], rec.get('built')),
             value_line=w['value_line'].format(value=value) if value else '', value_part=w['value_part'].format(value=value) if value else '',
             thr=str((rec.get('thr') or ['', ''])[1] or '15 min').strip())
    est = bool(rec.get('estimate'))
    f['measured'] = w['measured_est' if est else 'measured']
    f['how'] = w['how_est' if est else 'how'].format(**f)
    tok = rec.get('tokens') or [0, 0]
    dm = rec.get('days') or {}
    if tok[0] and tok[1] and not rec.get('estimate'):
        third = w['x3_tok'].format(read=_short(tok[0]), written=_short(tok[1]), **f)
        third = _cap(third, lang)
    elif dm:
        d, bm = max(dm.items(), key=lambda kv: kv[1])
        third = w['x3_day'].format(busy_time=w['t'](bm // 60, bm % 60), busy_day=DOW[lang][datetime.date.fromisoformat(d).weekday()], **f)
    else:
        third = w['x3_plain'].format(**f)
    return [(w['x'] + ' · 1', w['x1'].format(**f)), (w['x'] + ' · 2', w['x2'].format(**f)), (w['x'] + ' · 3', third),
            (w['li'], w['li_post'].format(**f)), (w['reel'], w['reel_post'].format(**f))]

def kit(rec, lang, quote, link, site, png=None, mp4=None):
    """The kit as Markdown: what to attach, one copyable block per post, and a few posting tips."""
    w = W[lang]
    attach = [f'- {w["png"]}: `{png}`'] if png else []
    attach += [f'- {w["mp4"]}: `{mp4}`'] if mp4 else []
    attach += [f'- {w["link"]}: {link}']
    out = [f'# {w["title"]} · {rec["name"]}', '', f'**{w["assets"]}**', *attach, '']
    for name, text in posts(rec, lang, quote, link, site):
        out += [f'## {name}', '', '```text', text, '```', '']
    out += [f'## {w["tips"]}', '', *[f'- {t}' for t in w['tip']], '']
    return '\n'.join(out)
