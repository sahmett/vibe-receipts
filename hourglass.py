#!/usr/bin/env python3
"""hourglass-ledger — bir git reposunda harcanan çalışma süresini tahmin eder.

İki bağımsız katman:
  1) Tahmin   — commit'ler arası süre × efor oranı (kod yoğunluğundan türer)
  2) Gerçek   — Claude Code oturum kayıtlarındaki (~/.claude/projects) olay zaman damgaları

Kullanım:
  python3 hourglass.py /path/to/repo
  python3 hourglass.py /path/to/repo --since 2026-06-01 --until 2026-06-30
  python3 hourglass.py /path/to/repo --calibrate     # KOD_ORANI'yı transcript'e oturt
"""
import argparse, datetime, glob, html, json, os, re, subprocess

# ===== EFOR ORANI MODELİ =====
# Efor oranı = 1 + (eklenen etkin kod × KOD_ORANI) / Ölçülen
# TOPLAM     = Ölçülen × Efor oranı
# Sabit "sallama" yüzde yok; uplift tamamen kod yoğunluğundan gelir.
BREAK     = 150*60    # bunu aşan boşluk = mola (0); altındaki tüm boşluk tam sayılır
KOD_ORANI = 0.02      # dk / eklenen etkin kod satırı (--calibrate ile transcript'e oturtulabilir)
TR_IDLE   = 15*60     # transcript: ardışık olay arası bu kadar boşluk = aktif; üstü = uzaklaşma

# Eklenen kod için ağırlık (sadece gerçek kod/config; docs/vendor/generated 0)
CODE_W = {'code':1.0, 'config':0.4, 'arch':0.0, 'doc':0.0, 'vendor':0.0, 'gen':0.0}

# Toplu kopyalanan/taşınan statik içerik — hesaba katılmaz. Projene göre genişlet.
VENDOR_RE=re.compile(r'(^|/)(prototypes/|_archive/|vendor/|third_party/)|(^|/)(src/)?ui/.*\.(html|css|js)$')
GEN_RE=re.compile(r'(pnpm-lock|package-lock|yarn\.lock|poetry\.lock|Cargo\.lock|payload-types|/migrations/|\.min\.(js|css)$)')

def kind(path):
    p=path.lower()
    if VENDOR_RE.search(p): return 'vendor'
    if GEN_RE.search(p): return 'gen'
    if any(x in p for x in ['/specs/','/adr/','-prd','architecture','constitution','/plan']) and p.endswith(('.md','.pages')): return 'arch'
    if p.endswith(('.md','.mdx','.pages','.txt','.rst')): return 'doc'
    if p.endswith(('.json','.yaml','.yml','.toml','.mjs','.npmrc','.nvmrc','.ini','.env.example')): return 'config'
    return 'code'

NOISE=re.compile(r'^(Merge pull request|Merge branch|Merge remote-tracking|index on |On \S+: )')
DOW_TR=['Pazartesi','Salı','Çarşamba','Perşembe','Cuma','Cumartesi','Pazar']

def hm(s):
    m=int(round(s/60)); return f"{m//60}s {m%60:02d}d"

def day_of(t): return datetime.datetime.fromtimestamp(t).strftime('%Y-%m-%d')

def dow(d): return DOW_TR[datetime.date.fromisoformat(d).weekday()]

def claude_dirs(repo):
    """Claude Code, proje yolundaki alfanümerik olmayan karakterleri '-' yapar.
    Repo klasörünü ve onun altındaki .claude/worktrees oturumlarını döndürür."""
    enc=re.sub(r'[^A-Za-z0-9]','-',repo)
    base=os.path.expanduser('~/.claude/projects')
    return [d for d in glob.glob(os.path.join(base,enc+'*'))
            if os.path.basename(d)==enc or os.path.basename(d).startswith(enc+'--claude-worktrees-')]

def load_commits(repo,author,since,until):
    cmd=['git','-C',repo,'log','--all','--no-merges','--reverse','--pretty=format:C|%at|%s','--numstat']
    if author: cmd.append(f'--author={author}')
    raw=subprocess.check_output(cmd,text=True,errors='ignore')
    commits=[];cur=None
    for ln in raw.splitlines():
        if ln.startswith('C|'):
            if cur: commits.append(cur)
            _,at,subj=ln.split('|',2); cur={'t':int(at),'subj':subj,'f':[]}
        elif ln.strip() and cur is not None:
            p=ln.split('\t')
            if len(p)==3: cur['f'].append(p)
    if cur: commits.append(cur)
    return [c for c in commits if not NOISE.match(c['subj']) and since<=day_of(c['t'])<=until]

def load_transcript(dirs,since,until):
    tts=set()
    for d in dirs:
        for tf in glob.glob(os.path.join(d,'*.jsonl')):
            for ln in open(tf,errors='ignore'):
                try: t=json.loads(ln).get('timestamp')
                except Exception: continue
                if not t: continue
                try: ts=datetime.datetime.fromisoformat(t.replace('Z','+00:00')).timestamp()
                except Exception: continue
                if since<=day_of(ts)<=until: tts.add(ts)
    return sorted(tts)

def main():
    ap=argparse.ArgumentParser(description='Git commit + Claude oturum kayıtlarından çalışma süresi analizi')
    ap.add_argument('repo',nargs='?',default='.',help='analiz edilecek git reposu (varsayılan: .)')
    ap.add_argument('--since',default='0000-00-00',help='başlangıç günü YYYY-MM-DD')
    ap.add_argument('--until',default='9999-99-99',help='bitiş günü YYYY-MM-DD')
    ap.add_argument('--author',help='sadece bu yazarın commit\'leri (git --author deseni)')
    ap.add_argument('--transcripts',action='append',help='Claude kayıt klasörü (otomatik bulunanı ezer, birden çok verilebilir)')
    ap.add_argument('--calibrate',action='store_true',help='KOD_ORANI\'yı transcript ölçümüne göre hesapla')
    ap.add_argument('--out',default=os.path.join(os.path.dirname(os.path.abspath(__file__)),'output'),help='çıktı klasörü')
    a=ap.parse_args()

    repo=os.path.realpath(a.repo)
    name=os.path.basename(repo)
    commits=load_commits(repo,a.author,a.since,a.until)
    if not commits: raise SystemExit('Bu aralıkta commit bulunamadı.')

    # --- günlük ölçülen (commit arası, oturum içi) + eklenen etkin kod ---
    dmeas={};dcode={};dcom={};dadd={};ddel={};dvendor={};dsubj={}
    for i,c in enumerate(commits):
        d=day_of(c['t'])
        dcom[d]=dcom.get(d,0)+1; dsubj.setdefault(d,[]).append(c['subj'])
        if i>0:
            g=c['t']-commits[i-1]['t']
            if g<=BREAK: dmeas[d]=dmeas.get(d,0)+g
        for ad,de,path in c['f']:
            if ad=='-' or de=='-': continue
            ad,de=int(ad),int(de)
            dadd[d]=dadd.get(d,0)+ad; ddel[d]=ddel.get(d,0)+de
            if kind(path)=='vendor': dvendor[d]=dvendor.get(d,0)+ad+de
            if '=>' in path and ad==0 and de==0: continue
            dcode[d]=dcode.get(d,0)+CODE_W[kind(path)]*ad   # sadece EKLENEN satır

    measured=sum(dmeas.values()); added_code=sum(dcode.values())

    # --- transcript (gerçek ölçüm) ---
    dirs=a.transcripts or claude_dirs(repo)
    tts=load_transcript(dirs,a.since,a.until)
    tr_active=0; dtract={}
    for i in range(1,len(tts)):
        g=tts[i]-tts[i-1]
        if g<=TR_IDLE:
            tr_active+=g; d=day_of(tts[i]); dtract[d]=dtract.get(d,0)+g
    has_tr=bool(tts)

    kod_orani=KOD_ORANI
    if a.calibrate:
        if not has_tr or not added_code: raise SystemExit('Kalibrasyon için transcript ve eklenen kod gerekli.')
        kod_orani=max(0.0,(tr_active-measured)/60/added_code)

    code_effort=added_code*kod_orani*60
    effort_ratio=(measured+code_effort)/measured if measured else 0
    total=measured+code_effort

    days=sorted(dcom)
    dcodeff={d:dcode.get(d,0)*kod_orani*60 for d in days}
    dratio={d:(dmeas.get(d,0)+dcodeff[d])/dmeas[d] if dmeas.get(d,0) else 0 for d in days}
    day_tot={d:dmeas.get(d,0)+dcodeff[d] for d in days}
    mx=max(day_tot.values()) or 1
    allrows=sum(dadd.values())+sum(ddel.values())
    vendor_pct=100*sum(dvendor.values())/allrows if allrows else 0
    d0,d1=days[0],days[-1]

    print(f"Repo             : {repo}")
    print(f"Aralık           : {d0} → {d1}  ({len(commits)} commit)")
    print(f"Ölçülen          : {hm(measured)}")
    print(f"Eklenen etkin kod: {added_code:.0f} satır")
    print(f"Kod eforu        : {hm(code_effort)}   ({added_code:.0f} × {kod_orani:.4f}dk)")
    print(f"EFOR ORANI       : {effort_ratio:.3f}")
    print(f"{'='*46}\nTAHMİN TOPLAM ≈ {hm(total)}   ({total/3600:.1f} saat)\n{'='*46}")
    if has_tr: print(f"Transcript gerçek aktif (IDLE {TR_IDLE//60}dk): {hm(tr_active)}  ({len(tts)} olay, {len(dirs)} klasör)")
    else:      print("Transcript bulunamadı — yalnız commit tahmini raporlanacak.")
    if a.calibrate: print(f"Kalibre KOD_ORANI: {kod_orani:.4f} dk/satır  (script başındaki KOD_ORANI'ya yazabilirsin)")

    # ===== HTML RAPOR =====
    e=html.escape
    def bar(v,m,c):
        w=0 if not m else v/m*100
        return f'<div class="bar"><div class="barfill" style="width:{w:.1f}%;background:{c}"></div></div>'

    P=[f'<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(name)} · Çalışma Analizi</title><style>{CSS}</style></head><body><div class="wrap">']
    sub=f'{len(commits)} commit' + (f' · {len(tts)} Claude olayı' if has_tr else '') + f' · {d0} → {d1}'
    P.append(f'<header><h1>📊 {e(name)} · Çalışma Süresi Analizi</h1><div class="sub">{sub}</div></header>')
    P.append('<div class="kpis">'
        + (f'<div class="kpi"><div class="v">{hm(tr_active)}</div><div class="l">Gerçek (Claude oturumları)</div></div>' if has_tr else '')
        + f'<div class="kpi"><div class="v">{hm(total)}</div><div class="l">Tahmin (commit modeli)</div></div>'
        + (f'<div class="kpi"><div class="v">~{hm(abs(tr_active-total))}</div><div class="l">İki yöntem farkı</div></div>' if has_tr else '')
        + f'<div class="kpi"><div class="v">{len(commits)}</div><div class="l">Commit</div></div></div>')

    if has_tr:
        mxv=max(tr_active,total) or 1
        P.append('<h2>🎯 İki Yöntemle Doğrulama</h2><div class="card">')
        P.append(f'<div class="scn"><div class="nm">🟢 Gerçek — Claude transcript aktif süresi</div>{bar(tr_active,mxv,"#34d399")}<div class="vl">{hm(tr_active)}</div></div>')
        P.append(f'<div class="scn"><div class="nm">🟣 Tahmin — commit efor-oranı modeli</div>{bar(total,mxv,"#a78bfa")}<div class="vl">{hm(total)}</div></div>')
        P.append(f'<div class="note">Transcript = {len(tts)} olaydan ölçülen aktif süre (ardışık olaylar arası ≤{TR_IDLE//60}dk). Asıl yer-gerçeği budur; commit modeli transcript\'i olmayan projeler için taşınabilir yaklaşıklıktır. Claude dışında elle yapılan iş transcript\'e girmez.</div></div>')

    P.append('<h2>⏱️ Süre Analizi</h2><div class="card">')
    P.append(f'<div class="formula">Efor oranı = 1 + (eklenen etkin kod × {kod_orani:.4f}dk) / Ölçülen = <b>{effort_ratio:.3f}</b><br>TOPLAM = Ölçülen × Efor oranı</div>')
    P.append(f'<div class="scn"><div class="nm">Ölçülen (commit arası)</div>{bar(measured,total,"#60a5fa")}<div class="vl">{hm(measured)}</div></div>')
    P.append(f'<div class="scn"><div class="nm">× Efor oranı ({effort_ratio:.2f}) — kod eforu</div>{bar(code_effort,total,"#fbbf24")}<div class="vl">+{hm(code_effort)}</div></div>')
    P.append(f'<div class="scn"><div class="nm"><b>TOPLAM</b></div>{bar(total,total,"#a78bfa")}<div class="vl">{hm(total)}</div></div>')
    P.append(f'<div class="note">Molalar (>{BREAK//60}dk) ve kopya/vendor satırlar dışlandı. Ham satırların %{vendor_pct:.0f}\'i kopya/vendor.</div>')
    P.append('<div style="margin:10px 0"><span class="wt">kod ×1.0</span><span class="wt">config ×0.4</span><span class="wt">docs ×0</span><span class="wt">kopya/vendor ×0</span><span class="wt">üretilmiş ×0</span></div></div>')

    trdays=sorted(set(days)|set(dtract))
    P.append('<h2>📅 Günlük Çalışma & Kod</h2><div class="card"><div class="scroll"><table>')
    P.append('<tr><th>Tarih</th><th>Gün</th><th class="r">Commit</th><th class="r">Ölçülen</th><th class="r">Efor oranı</th><th>Tahmin</th>'
             + ('<th class="r">🟢 Gerçek</th>' if has_tr else '') + '<th class="r">Satır +/−</th></tr>')
    for d in trdays:
        P.append(f'<tr><td>{d[5:]}</td><td>{dow(d)}</td><td class="r">{dcom.get(d,0)}</td><td class="r">{hm(dmeas.get(d,0))}</td>'
                 f'<td class="r">{("×"+format(dratio.get(d,0),".2f")) if dratio.get(d,0) else "—"}</td>'
                 f'<td><div style="display:flex;align-items:center;gap:8px">{bar(day_tot.get(d,0),mx,"#a78bfa")}<span style="font-size:13px;width:52px">{hm(day_tot.get(d,0))}</span></div></td>'
                 + (f'<td class="r" style="color:#34d399;font-weight:700">{hm(dtract.get(d,0))}</td>' if has_tr else '')
                 + f'<td class="r" style="color:#86efac">+{dadd.get(d,0):,}<span style="color:#fca5a5"> / −{ddel.get(d,0):,}</span></td></tr>')
    P.append(f'<tr class="tot"><td colspan="2">TOPLAM</td><td class="r">{len(commits)}</td><td class="r">{hm(measured)}</td><td class="r">×{effort_ratio:.2f}</td><td>{hm(total)}</td>'
             + (f'<td class="r" style="color:#34d399">{hm(tr_active)}</td>' if has_tr else '')
             + f'<td class="r">+{sum(dadd.values()):,} / −{sum(ddel.values()):,}</td></tr>')
    P.append('</table></div></div>')

    P.append('<h2>📝 Günlük Commit Özeti</h2>')
    for d in days:
        items=''.join(f'<li>{e(s)}</li>' for s in dsubj[d])
        P.append(f'<div class="dayblk"><h3>{d[5:]} · {dow(d)} <span class="hrs">{hm(day_tot[d])} · {dcom[d]} commit</span></h3><ul>{items}</ul></div>')

    P.append(f'<div class="foot">hourglass-ledger · {e(name)} · {datetime.date.today()}</div></div></body></html>')

    os.makedirs(a.out,exist_ok=True)
    out=os.path.join(a.out,f'{name}-rapor.html')
    open(out,'w',encoding='utf-8').write('\n'.join(P))
    csvp=os.path.join(a.out,f'{name}-gunluk.csv')
    with open(csvp,'w',encoding='utf-8') as f:
        f.write('tarih,commit,olculen_dk,kod_eforu_dk,tahmin_dk,gercek_dk,eklenen,silinen\n')
        for d in trdays:
            f.write(f'{d},{dcom.get(d,0)},{dmeas.get(d,0)/60:.0f},{dcodeff.get(d,0)/60:.0f},{day_tot.get(d,0)/60:.0f},{dtract.get(d,0)/60:.0f},{dadd.get(d,0)},{ddel.get(d,0)}\n')
    print("HTML:",out); print("CSV :",csvp)

CSS="""*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,'Segoe UI',Roboto,sans-serif;background:#0f1117;color:#e6e8ee;line-height:1.55;padding:40px 16px}
.wrap{max-width:920px;margin:0 auto}
h1{font-size:28px;font-weight:800;letter-spacing:-.5px}
h2{font-size:19px;margin:36px 0 14px;padding-bottom:8px;border-bottom:1px solid #272b36;color:#fff}
.sub{color:#8b90a0;margin-top:6px;font-size:14px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin-top:26px}
.kpi{background:#171a23;border:1px solid #242938;border-radius:14px;padding:18px}
.kpi .v{font-size:25px;font-weight:800;color:#a78bfa}.kpi .l{font-size:12px;color:#8b90a0;margin-top:4px;text-transform:uppercase;letter-spacing:.5px}
.card{background:#171a23;border:1px solid #242938;border-radius:14px;padding:22px;margin-top:14px}
.scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:10px;border-bottom:1px solid #242938;white-space:nowrap}
th{color:#8b90a0;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.4px}
td.r,th.r{text-align:right}tr:last-child td{border-bottom:none}
.tot{font-weight:700;color:#fff;background:#1c2030}
.bar{background:#242938;border-radius:6px;height:22px;overflow:hidden;min-width:70px;flex:1}.barfill{height:100%;border-radius:6px}
.scn{display:flex;align-items:center;gap:12px;margin:10px 0}.scn .nm{width:200px;font-size:13px;color:#c8ccd8}.scn .vl{width:70px;text-align:right;font-weight:700;font-size:14px}
.note{font-size:12.5px;color:#8b90a0;margin-top:10px;font-style:italic}
.formula{background:#13161f;border:1px solid #242938;border-radius:10px;padding:14px 16px;font-family:ui-monospace,monospace;font-size:13px;color:#c4b5fd;margin:4px 0 14px}
.dayblk{background:#13161f;border:1px solid #242938;border-radius:12px;padding:14px 16px;margin-top:12px}
.dayblk h3{font-size:15px;color:#fff;display:flex;justify-content:space-between}.dayblk h3 .hrs{font-size:13px;color:#a78bfa;font-weight:700}
.dayblk ul{margin:8px 0 0 18px}.dayblk li{font-size:13.5px;color:#aeb3c2;margin:5px 0}
.foot{text-align:center;color:#5d6273;font-size:12px;margin-top:38px}
.wt{display:inline-block;background:#2a2147;color:#c4b5fd;border-radius:6px;padding:2px 8px;font-size:12px;font-weight:600;margin:2px}"""

if __name__=='__main__':
    main()
