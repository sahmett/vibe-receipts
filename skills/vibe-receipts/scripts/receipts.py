#!/usr/bin/env python3
"""vibe-receipts — how many hours did you really work on a git repo?

Two independent layers:
  1) Estimate      — gaps between commits × an effort ratio derived from code density
  2) Ground truth  — event timestamps in Claude Code session logs (~/.claude/projects)

Usage:
  python3 receipts.py /path/to/repo
  python3 receipts.py /path/to/repo --since 2026-06-01 --until 2026-06-30
  python3 receipts.py /path/to/repo --calibrate     # fit CODE_RATE to the transcript total
  python3 receipts.py /path/to/repo --lang tr       # Türkçe rapor
"""
import argparse, datetime, glob, html, json, os, re, subprocess

# ===== EFFORT RATIO MODEL =====
# Effort ratio = 1 + (effective added code × CODE_RATE) / Measured
# TOTAL        = Measured × Effort ratio
# No fixed "fudge" percentage; the uplift comes entirely from code density.
BREAK     = 150*60    # a gap longer than this = break (0); every shorter gap counts in full
CODE_RATE = 0.02      # minutes per effective added line (fit it with --calibrate)
TR_IDLE   = 15*60     # transcript: gap between events up to this = active; above = away

# Weights for added lines (only real code/config; docs/vendor/generated weigh 0)
CODE_W = {'code':1.0, 'config':0.4, 'arch':0.0, 'doc':0.0, 'vendor':0.0, 'gen':0.0}

# Bulk-copied/moved static content — excluded. Extend for your project.
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

L={
 'en':dict(
   h='h',m='m',dow=['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'],
   title='Work Time Receipt',commits='commits',events='Claude events',
   k_real='Real (Claude sessions)',k_est='Estimate (commit model)',k_diff='Gap between methods',k_com='Commits',
   s_verify='🎯 Two-method check',v_real='🟢 Real — Claude transcript active time',v_est='🟣 Estimate — commit effort-ratio model',
   v_note='Transcript = active time measured from {n} events (gaps ≤{idle}m between events). This is the ground truth; the commit model is a portable approximation for projects without transcripts. Work done outside Claude Code is not in the transcript.',
   s_time='⏱️ Time breakdown',f_ratio='Effort ratio',f_added='effective added code',f_meas='Measured',f_total='TOTAL',
   t_meas='Measured (between commits)',t_code='× Effort ratio ({r}) — code effort',
   t_note='Breaks (>{b}m) and copied/vendor lines excluded. {p}% of raw lines were copied/vendor.',
   w=['code ×1.0','config ×0.4','docs ×0','copied/vendor ×0','generated ×0'],
   s_daily='📅 Daily work & code',c=['Date','Day','Commits','Measured','Effort','Estimate','🟢 Real','Lines +/−'],tot='TOTAL',
   s_sum='📝 Daily commit log',
   p_repo='Repo',p_range='Range',p_meas='Measured',p_code='Effective code',p_lines='lines',p_eff='Code effort',p_ratio='EFFORT RATIO',p_total='ESTIMATED TOTAL',
   p_tr='Transcript active (idle {idle}m)',p_ev='events',p_dirs='folders',p_notr='No transcripts found — commit estimate only.',
   p_cal='Calibrated CODE_RATE: {v:.4f} min/line (write it into CODE_RATE at the top of the script)',
   e_none='No commits found in this range.',e_cal='Calibration needs both transcripts and added code.'),
 'tr':dict(
   h='s',m='d',dow=['Pazartesi','Salı','Çarşamba','Perşembe','Cuma','Cumartesi','Pazar'],
   title='Çalışma Süresi Fişi',commits='commit',events='Claude olayı',
   k_real='Gerçek (Claude oturumları)',k_est='Tahmin (commit modeli)',k_diff='İki yöntem farkı',k_com='Commit',
   s_verify='🎯 İki yöntemle doğrulama',v_real='🟢 Gerçek — Claude transcript aktif süresi',v_est='🟣 Tahmin — commit efor-oranı modeli',
   v_note='Transcript = {n} olaydan ölçülen aktif süre (ardışık olaylar arası ≤{idle}dk). Asıl yer-gerçeği budur; commit modeli transcript\'i olmayan projeler için taşınabilir yaklaşıklıktır. Claude dışında elle yapılan iş transcript\'e girmez.',
   s_time='⏱️ Süre analizi',f_ratio='Efor oranı',f_added='eklenen etkin kod',f_meas='Ölçülen',f_total='TOPLAM',
   t_meas='Ölçülen (commit arası)',t_code='× Efor oranı ({r}) — kod eforu',
   t_note='Molalar (>{b}dk) ve kopya/vendor satırlar dışlandı. Ham satırların %{p}\'i kopya/vendor.',
   w=['kod ×1.0','config ×0.4','docs ×0','kopya/vendor ×0','üretilmiş ×0'],
   s_daily='📅 Günlük çalışma & kod',c=['Tarih','Gün','Commit','Ölçülen','Efor','Tahmin','🟢 Gerçek','Satır +/−'],tot='TOPLAM',
   s_sum='📝 Günlük commit özeti',
   p_repo='Repo',p_range='Aralık',p_meas='Ölçülen',p_code='Eklenen etkin kod',p_lines='satır',p_eff='Kod eforu',p_ratio='EFOR ORANI',p_total='TAHMİN TOPLAM',
   p_tr='Transcript gerçek aktif (IDLE {idle}dk)',p_ev='olay',p_dirs='klasör',p_notr='Transcript bulunamadı — yalnız commit tahmini raporlanacak.',
   p_cal='Kalibre CODE_RATE: {v:.4f} dk/satır (script başındaki CODE_RATE\'e yazabilirsin)',
   e_none='Bu aralıkta commit bulunamadı.',e_cal='Kalibrasyon için transcript ve eklenen kod gerekli.'),
}

def default_lang():
    loc=os.environ.get('LC_ALL') or os.environ.get('LC_MESSAGES') or os.environ.get('LANG') or ''
    return 'tr' if loc.lower().startswith('tr') else 'en'

def day_of(t): return datetime.datetime.fromtimestamp(t).strftime('%Y-%m-%d')

def claude_dirs(repo):
    """Claude Code turns every non-alphanumeric character of the project path into '-'.
    Returns the repo's folder plus sessions under its .claude/worktrees."""
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
    # --all does not guarantee time order (rebases, cherry-picks); sort by author time and
    # drop rebased copies of the same commit (same author time + subject).
    seen=set(); out=[]
    for c in sorted(commits,key=lambda c:c['t']):
        k=(c['t'],c['subj'])
        if k in seen or NOISE.match(c['subj']) or not since<=day_of(c['t'])<=until: continue
        seen.add(k); out.append(c)
    return out

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
    ap=argparse.ArgumentParser(description='Working-time report from git commits + Claude Code session logs')
    ap.add_argument('repo',nargs='?',default='.',help='git repo to analyse (default: .)')
    ap.add_argument('--since',default='0000-00-00',help='first day YYYY-MM-DD')
    ap.add_argument('--until',default='9999-99-99',help='last day YYYY-MM-DD')
    ap.add_argument('--author',help='only commits by this author (git --author pattern)')
    ap.add_argument('--transcripts',action='append',help='Claude log folder (overrides auto-detection, repeatable)')
    ap.add_argument('--calibrate',action='store_true',help='fit CODE_RATE to the transcript measurement')
    ap.add_argument('--lang',choices=sorted(L),default=default_lang(),help='report language (default: from $LANG, else en)')
    ap.add_argument('--name',help='project name shown in the report (default: repo folder name)')
    ap.add_argument('--out',default=os.path.expanduser('~/vibe-receipts'),help='output folder (default ~/vibe-receipts)')
    a=ap.parse_args()
    T=L[a.lang]

    def hm(s):
        mm=int(round(s/60)); return f"{mm//60}{T['h']} {mm%60:02d}{T['m']}"
    def dow(d): return T['dow'][datetime.date.fromisoformat(d).weekday()]

    repo=os.path.realpath(a.repo)
    name=a.name or os.path.basename(repo)
    commits=load_commits(repo,a.author,a.since,a.until)
    if not commits: raise SystemExit(T['e_none'])

    # --- daily measured (between commits, within a session) + effective added code ---
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
            dcode[d]=dcode.get(d,0)+CODE_W[kind(path)]*ad   # ADDED lines only

    measured=sum(dmeas.values()); added_code=sum(dcode.values())

    # --- transcript (ground truth) ---
    dirs=a.transcripts or claude_dirs(repo)
    tts=load_transcript(dirs,a.since,a.until)
    tr_active=0; dtract={}
    for i in range(1,len(tts)):
        g=tts[i]-tts[i-1]
        if g<=TR_IDLE:
            tr_active+=g; d=day_of(tts[i]); dtract[d]=dtract.get(d,0)+g
    has_tr=bool(tts)

    rate=CODE_RATE
    if a.calibrate:
        if not has_tr or not added_code: raise SystemExit(T['e_cal'])
        rate=max(0.0,(tr_active-measured)/60/added_code)

    code_effort=added_code*rate*60
    effort_ratio=(measured+code_effort)/measured if measured else 0
    total=measured+code_effort

    days=sorted(dcom)
    dcodeff={d:dcode.get(d,0)*rate*60 for d in days}
    dratio={d:(dmeas.get(d,0)+dcodeff[d])/dmeas[d] if dmeas.get(d,0) else 0 for d in days}
    day_tot={d:dmeas.get(d,0)+dcodeff[d] for d in days}
    mx=max(day_tot.values()) or 1
    allrows=sum(dadd.values())+sum(ddel.values())
    vendor_pct=100*sum(dvendor.values())/allrows if allrows else 0
    d0,d1=days[0],days[-1]

    print(f"{T['p_repo']:<17}: {repo}")
    print(f"{T['p_range']:<17}: {d0} → {d1}  ({len(commits)} {T['commits']})")
    print(f"{T['p_meas']:<17}: {hm(measured)}")
    print(f"{T['p_code']:<17}: {added_code:.0f} {T['p_lines']}")
    print(f"{T['p_eff']:<17}: {hm(code_effort)}   ({added_code:.0f} × {rate:.4f})")
    print(f"{T['p_ratio']:<17}: {effort_ratio:.3f}")
    print(f"{'='*46}\n{T['p_total']} ≈ {hm(total)}   ({total/3600:.1f})\n{'='*46}")
    if has_tr: print(f"{T['p_tr'].format(idle=TR_IDLE//60)}: {hm(tr_active)}  ({len(tts)} {T['p_ev']}, {len(dirs)} {T['p_dirs']})")
    else:      print(T['p_notr'])
    if a.calibrate: print(T['p_cal'].format(v=rate))

    # ===== HTML REPORT =====
    e=html.escape
    def bar(v,m,c):
        w=0 if not m else v/m*100
        return f'<div class="bar"><div class="barfill" style="width:{w:.1f}%;background:{c}"></div></div>'

    P=[f'<!doctype html><html lang="{a.lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(name)} · {T["title"]}</title><style>{CSS}</style></head><body><div class="wrap">']
    sub=f'{len(commits)} {T["commits"]}' + (f' · {len(tts):,} {T["events"]}' if has_tr else '') + f' · {d0} → {d1}'
    P.append(f'<header><h1>🧾 {e(name)} · {T["title"]}</h1><div class="sub">{sub}</div></header>')
    P.append('<div class="kpis">'
        + (f'<div class="kpi"><div class="v">{hm(tr_active)}</div><div class="l">{T["k_real"]}</div></div>' if has_tr else '')
        + f'<div class="kpi"><div class="v">{hm(total)}</div><div class="l">{T["k_est"]}</div></div>'
        + (f'<div class="kpi"><div class="v">~{hm(abs(tr_active-total))}</div><div class="l">{T["k_diff"]}</div></div>' if has_tr else '')
        + f'<div class="kpi"><div class="v">{len(commits)}</div><div class="l">{T["k_com"]}</div></div></div>')

    if has_tr:
        mxv=max(tr_active,total) or 1
        P.append(f'<h2>{T["s_verify"]}</h2><div class="card">')
        P.append(f'<div class="scn"><div class="nm">{T["v_real"]}</div>{bar(tr_active,mxv,"#34d399")}<div class="vl">{hm(tr_active)}</div></div>')
        P.append(f'<div class="scn"><div class="nm">{T["v_est"]}</div>{bar(total,mxv,"#a78bfa")}<div class="vl">{hm(total)}</div></div>')
        P.append(f'<div class="note">{e(T["v_note"].format(n=f"{len(tts):,}",idle=TR_IDLE//60))}</div></div>')

    P.append(f'<h2>{T["s_time"]}</h2><div class="card">')
    P.append(f'<div class="formula">{T["f_ratio"]} = 1 + ({T["f_added"]} × {rate:.4f}) / {T["f_meas"]} = <b>{effort_ratio:.3f}</b><br>{T["f_total"]} = {T["f_meas"]} × {T["f_ratio"]}</div>')
    P.append(f'<div class="scn"><div class="nm">{T["t_meas"]}</div>{bar(measured,total,"#60a5fa")}<div class="vl">{hm(measured)}</div></div>')
    P.append(f'<div class="scn"><div class="nm">{T["t_code"].format(r=f"{effort_ratio:.2f}")}</div>{bar(code_effort,total,"#fbbf24")}<div class="vl">+{hm(code_effort)}</div></div>')
    P.append(f'<div class="scn"><div class="nm"><b>{T["f_total"]}</b></div>{bar(total,total,"#a78bfa")}<div class="vl">{hm(total)}</div></div>')
    P.append(f'<div class="note">{e(T["t_note"].format(b=BREAK//60,p=f"{vendor_pct:.0f}"))}</div>')
    P.append('<div style="margin:10px 0">'+''.join(f'<span class="wt">{w}</span>' for w in T['w'])+'</div></div>')

    trdays=sorted(set(days)|set(dtract))
    C=T['c']
    P.append(f'<h2>{T["s_daily"]}</h2><div class="card"><div class="scroll"><table>')
    P.append(f'<tr><th>{C[0]}</th><th>{C[1]}</th><th class="r">{C[2]}</th><th class="r">{C[3]}</th><th class="r">{C[4]}</th><th>{C[5]}</th>'
             + (f'<th class="r">{C[6]}</th>' if has_tr else '') + f'<th class="r">{C[7]}</th></tr>')
    for d in trdays:
        P.append(f'<tr><td>{d[5:]}</td><td>{dow(d)}</td><td class="r">{dcom.get(d,0)}</td><td class="r">{hm(dmeas.get(d,0))}</td>'
                 f'<td class="r">{("×"+format(dratio.get(d,0),".2f")) if dratio.get(d,0) else "—"}</td>'
                 f'<td><div style="display:flex;align-items:center;gap:8px">{bar(day_tot.get(d,0),mx,"#a78bfa")}<span style="font-size:13px;width:52px">{hm(day_tot.get(d,0))}</span></div></td>'
                 + (f'<td class="r" style="color:#34d399;font-weight:700">{hm(dtract.get(d,0))}</td>' if has_tr else '')
                 + f'<td class="r" style="color:#86efac">+{dadd.get(d,0):,}<span style="color:#fca5a5"> / −{ddel.get(d,0):,}</span></td></tr>')
    P.append(f'<tr class="tot"><td colspan="2">{T["tot"]}</td><td class="r">{len(commits)}</td><td class="r">{hm(measured)}</td><td class="r">×{effort_ratio:.2f}</td><td>{hm(total)}</td>'
             + (f'<td class="r" style="color:#34d399">{hm(tr_active)}</td>' if has_tr else '')
             + f'<td class="r">+{sum(dadd.values()):,} / −{sum(ddel.values()):,}</td></tr>')
    P.append('</table></div></div>')

    P.append(f'<h2>{T["s_sum"]}</h2>')
    for d in days:
        items=''.join(f'<li>{e(s)}</li>' for s in dsubj[d])
        P.append(f'<div class="dayblk"><h3>{d[5:]} · {dow(d)} <span class="hrs">{hm(day_tot[d])} · {dcom[d]} {T["commits"]}</span></h3><ul>{items}</ul></div>')

    P.append(f'<div class="foot">🧾 vibe-receipts · {e(name)} · {datetime.date.today()}</div></div></body></html>')

    os.makedirs(a.out,exist_ok=True)
    out=os.path.join(a.out,f'{name}-report.html')
    open(out,'w',encoding='utf-8').write('\n'.join(P))
    csvp=os.path.join(a.out,f'{name}-daily.csv')
    with open(csvp,'w',encoding='utf-8') as f:
        f.write('date,commits,measured_min,code_effort_min,estimate_min,real_min,added,deleted\n')
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
