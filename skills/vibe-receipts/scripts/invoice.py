"""One client's archived receipts as an invoice (with --rate) or a timesheet (without), for receipts.py --invoice.

Page 1: who it is from and to, one line per receipt (project, period, hours, and with a rate its amount), the
totals. After it: every receipt's own lines (the days or weeks and their time), and how the time was measured.
Written as HTML and, with Chrome, as an A4 PDF: <out>/invoices/<client>_<number>.html and .pdf."""
import datetime, glob, html, json, os, pathlib, re, subprocess

L = {
 'en': dict(invoice='Invoice', timesheet='Timesheet', no='No.', date='Date', period='Period', frm='From', to='Bill to', client='Client',
            project='Project', hours='Hours', rate='Rate', amount='Amount', total_hours='Total hours', subtotal='Subtotal',
            tax='Tax ({p}%)', total='Total due', detail='Time detail', thr='break threshold',
            method="Time is measured from the gaps between the developer's own Claude Code prompts. A gap longer than the "
                   'break threshold counts as a break, not as work. Commit-only receipts are estimated from commit sessions.',
            made='Measured with Slipt', est='commit estimate',
            none='No receipts for "{c}" with status "{s}". Run receipts.py on the project with --client "{c}" first.'),
 'tr': dict(invoice='Fatura', timesheet='Çalışma çizelgesi', no='No', date='Tarih', period='Dönem', frm='Gönderen', to='Alıcı', client='Müşteri',
            project='Proje', hours='Saat', rate='Ücret', amount='Tutar', total_hours='Toplam saat', subtotal='Ara toplam',
            tax='KDV (%{p})', total='Ödenecek tutar', detail='Süre dökümü', thr='mola sınırı',
            method="Süre, geliştiricinin kendi Claude Code prompt'ları arasındaki aralıklardan ölçülür. Mola sınırından uzun "
                   'bir aralık çalışma değil mola sayılır. Yalnızca commit içeren fişler commit oturumlarından tahmin edilir.',
            made='Slipt ile ölçüldü', est='commit tahmini',
            none='"{c}" için "{s}" durumunda fiş yok. Önce projede receipts.py\'yi --client "{c}" ile çalıştır.'),
}
SYM = {'USD': '$', 'EUR': '€', 'GBP': '£', 'TRY': '₺'}

def money(v, cur, lang):
    s = f'{v:,.2f}'
    if lang == 'tr': s = s.replace(',', ' ').replace('.', ',').replace(' ', '.')
    sym = SYM.get(cur.upper())
    if not sym: return f'{s} {cur.upper()}'
    return f'{s} {sym}' if lang == 'tr' else f'{sym}{s}'

def hours(m, lang):
    s = f'{m / 60:,.2f}'
    return s.replace(',', ' ').replace('.', ',').replace(' ', '.') if lang == 'tr' else s

def hm(m, lang):
    h, mm = ('s', 'd') if lang == 'tr' else ('h', 'm')
    return f'{m // 60}{h} {m % 60:02d}{mm}'

CSS = """
@page{size:A4;margin:16mm 16mm 18mm}
*{box-sizing:border-box}
html{-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{margin:0;color:#0b0b0c;font:400 10.5pt/1.5 system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",sans-serif;-webkit-font-smoothing:antialiased}
.mono{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace}
.page{max-width:178mm;margin:0 auto}
header{display:flex;justify-content:space-between;align-items:flex-start;gap:24px;padding-bottom:18px;border-bottom:1.5px solid #0b0b0c}
h1{margin:0;font-size:22pt;line-height:1.1;font-weight:650;letter-spacing:-.02em}
h1 i{display:inline-block;width:8px;height:8px;border-radius:50%;background:#E5322C;margin-left:6px;vertical-align:6px}
.meta{display:grid;grid-template-columns:auto auto;gap:3px 16px;font-size:9.5pt;text-align:right}
.meta span{color:#6d6d70}
.parties{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin:22px 0 26px}
.parties h2,.sec{margin:0 0 6px;font-size:8.5pt;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:#6d6d70}
.parties p{margin:0;white-space:pre-line}
.parties b{font-weight:600}
table{width:100%;border-collapse:collapse}
th{font-size:8.5pt;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:#6d6d70;text-align:left;padding:0 8px 8px 0;border-bottom:1px solid #d4d4d8}
td{padding:9px 8px 9px 0;border-bottom:1px solid #ececee;vertical-align:top}
th.r,td.r{text-align:right;padding-right:0}
td .sub{display:block;color:#6d6d70;font-size:9pt}
.tot{margin-left:auto;width:64%;margin-top:14px}
.tot div{display:flex;justify-content:space-between;padding:5px 0}
.tot .grand{margin-top:6px;padding-top:10px;border-top:1.5px solid #0b0b0c;font-size:13pt;font-weight:650}
.detail{break-before:page}
.detail h3{margin:22px 0 4px;font-size:11pt;font-weight:600}
.detail h3 span{font-weight:400;color:#6d6d70;font-size:9.5pt;margin-left:8px}
.detail table{font-size:9.5pt}
.detail td{padding:5px 8px 5px 0}
.how{margin-top:26px;padding-top:12px;border-top:1px solid #ececee;color:#56565b;font-size:9pt}
footer{margin-top:28px;color:#8d8d92;font-size:8.5pt;display:flex;justify-content:space-between}
"""

def page(T, lang, recs, client, number, today, rate, cur, tax, bill_from, bill_to):
    e = html.escape
    kind = T['invoice'] if rate else T['timesheet']
    start, end = min(r['start'] for r in recs), max(r['end'] for r in recs)
    total_min = sum(r['min'] for r in recs)
    amount = lambda r: round(r['min'] / 60 * rate, 2)
    head = (f'<th>{T["project"]}</th><th>{T["period"]}</th><th class="r">{T["hours"]}</th>'
            + (f'<th class="r">{T["rate"]}</th><th class="r">{T["amount"]}</th>' if rate else ''))
    built = lambda r: '<span class="sub">' + e(r['built']) + '</span>' if r.get('built') else ''
    thr = lambda r: ' · ' + T['thr'] + ' ' + e(r['thr'][1]) if r.get('thr') and len(r['thr']) > 1 and r['thr'][1] else ''
    rows = ''.join(
        f'<tr><td><b>{e(r["name"])}</b>{built(r)}</td>'
        f'<td class="mono">{e(r["start"])} – {e(r["end"])}</td>'
        f'<td class="r mono">{hours(r["min"], lang)}<span class="sub">{hm(r["min"], lang)}{" · " + T["est"] if r.get("estimate") else ""}</span></td>'
        + (f'<td class="r mono">{money(rate, cur, lang)}</td><td class="r mono">{money(amount(r), cur, lang)}</td>' if rate else '')
        + '</tr>' for r in recs)
    sub = round(sum(amount(r) for r in recs), 2) if rate else 0
    vat = round(sub * tax / 100, 2) if rate and tax else 0
    tot = (f'<div><span>{T["total_hours"]}</span><span class="mono">{hours(total_min, lang)} · {hm(total_min, lang)}</span></div>'
           + (f'<div><span>{T["subtotal"]}</span><span class="mono">{money(sub, cur, lang)}</span></div>'
              + (f'<div><span>{T["tax"].format(p=format(tax, "g"))}</span><span class="mono">{money(vat, cur, lang)}</span></div>' if tax else '')
              + f'<div class="grand"><span>{T["total"]}</span><span class="mono">{money(sub + vat, cur, lang)}</span></div>' if rate else ''))
    detail = ''.join(
        f'<h3>{e(r["name"])}<span class="mono">{e(r["start"])} – {e(r["end"])} · {hm(r["min"], lang)}{thr(r)}</span></h3>'
        f'<table><tr><th>{e(r["L"]["item"])}</th><th class="r">{e(r["L"]["qty"])}</th><th class="r">{e(r["L"]["time"])}</th></tr>'
        + ''.join(f'<tr><td>{e(str(i[1]))}</td><td class="r mono">{int(i[0]):,}</td><td class="r mono">{hm(int(i[2]), lang)}</td></tr>' for i in r['items'])
        + '</table>' for r in recs)
    party = lambda t, fallback: e(t).replace('\\n', '\n') if t else fallback   # "\n" typed on the command line is a line break
    to_extra = '\n' + party(bill_to, '') if bill_to else ''
    return (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><title>{e(kind)} {e(number)} · {e(client)}</title>'
            f'<style>{CSS}</style></head><body><div class="page">'
            f'<header><h1>{e(kind)}<i></i></h1><div class="meta"><span>{T["no"]}</span><b class="mono">{e(number)}</b>'
            f'<span>{T["date"]}</span><b class="mono">{today}</b><span>{T["period"]}</span><b class="mono">{start} – {end}</b></div></header>'
            f'<div class="parties"><div><h2>{T["frm"]}</h2><p>{party(bill_from, "—")}</p></div>'
            f'<div><h2>{T["to"] if rate else T["client"]}</h2><p><b>{e(client)}</b>{to_extra}</p></div></div>'
            f'<table><tr>{head}</tr>{rows}</table><div class="tot">{tot}</div>'
            f'<footer><span>{T["made"]}</span><span class="mono">{e(number)}</span></footer>'
            f'<section class="detail"><p class="sec">{T["detail"]}</p>{detail}<p class="how">{T["method"]}</p>'
            f'<footer><span>{T["made"]}</span><span class="mono">{e(client)} · {e(number)}</span></footer></section>'
            '</div></body></html>')

def build_invoice(out, client, lang, chrome=None, status='due', since='0000-00-00', until='9999-99-99', rate=None,
                  currency=None, tax=0, bill_from=None, bill_to=None, number=None, mark_billed=False):
    """Returns (html path, pdf path or None, the receipts on it). Raises SystemExit when nothing matches."""
    T = L[lang]; cur = currency or ('TRY' if lang == 'tr' else 'USD')
    paths, recs = {}, []
    for p in glob.glob(os.path.join(out, 'archive', '*.json')):
        try: r = json.load(open(p, encoding='utf-8'))
        except (OSError, ValueError): continue
        if (r.get('client') or '').strip().lower() == client.strip().lower() and r.get('status') == status \
                and since <= r.get('end', '') <= until:
            recs.append(r); paths[r['key']] = p
    if not recs: raise SystemExit(T['none'].format(c=client, s=status))
    recs.sort(key=lambda r: (r['start'], r['end']))
    client = recs[-1]['client'].strip()   # as it was archived, whatever case it was typed in here
    today = datetime.date.today().isoformat()
    inv = os.path.join(out, 'invoices'); os.makedirs(inv, exist_ok=True)
    if not number:   # this year's next number: 2026-001, 2026-002, ...
        n = len(glob.glob(os.path.join(inv, f'*_{today[:4]}-*.html')))
        number = f'{today[:4]}-{n + 1:03d}'
    base = os.path.join(inv, re.sub(r'[^A-Za-z0-9._-]', '-', client) + '_' + re.sub(r'[^A-Za-z0-9._-]', '-', number))
    with open(base + '.html', 'w', encoding='utf-8') as f:
        f.write(page(T, lang, recs, client, number, today, rate, cur, tax, bill_from, bill_to))
    pdf = None
    if chrome:
        dst = base + '.pdf'
        if os.path.exists(dst): os.remove(dst)
        try:
            subprocess.run([chrome, '--headless', '--disable-gpu', '--no-sandbox', '--no-pdf-header-footer', '--print-to-pdf-no-header',
                            f'--print-to-pdf={dst}', pathlib.Path(base + '.html').as_uri()], capture_output=True, timeout=120)
        except (OSError, subprocess.SubprocessError): pass
        pdf = dst if os.path.exists(dst) else None
    if mark_billed:   # these receipts move to the board's "billed" column
        for r in recs:
            r['status'] = 'paid'
            with open(paths[r['key']], 'w', encoding='utf-8') as f: json.dump(r, f, ensure_ascii=False, indent=1)
    return base + '.html', pdf, recs
