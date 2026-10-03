#!/usr/bin/env python3
"""vibe-receipts — how many hours did you really work on a git repo with Claude?

Working time = sum of the gaps between YOUR consecutive prompts in Claude Code session
logs (~/.claude/projects). A gap up to your break threshold counts as work, anything longer
is a break. By default the threshold is computed from your own gaps with Tukey's rule
(Q3 + 1.5·IQR); pass --idle MIN to use a fixed one. Commits only add context (what got built). For repos with
no session logs, a rough commit-gap estimate is used as a fallback.

Usage:
  python3 receipts.py /path/to/repo
  python3 receipts.py /path/to/repo --since 2026-06-01 --until 2026-06-30
  python3 receipts.py /path/to/repo --idle 20       # fixed 20-minute break threshold
  python3 receipts.py /path/to/repo --lang tr       # Türkçe rapor
"""
import argparse, datetime, glob, html, json, os, re, subprocess

IDLE       = 15            # minutes: fallback threshold when there are too few gaps for Tukey
MIN_GAPS   = 20            # fewer gaps than this = Tukey threshold is not reliable
SENS       = [5,10,15,20,30,45,60]   # thresholds shown in the sensitivity table
BANDS      = [(0,2),(2,5),(5,15),(15,30),(30,60),(60,None)]

# Fallback commit estimate (only used when there are no session logs)
BREAK      = 150*60        # gap between commits longer than this = break
CODE_RATE  = 0.02          # minutes per effective added line

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
# "user" records you did not type: IDE context, slash-command echoes, system/harness injections
NOISE_TAG=re.compile(r'<(ide_opened_file|ide_selection|command-name|command-message|command-args|local-command|system-reminder|task-notification)')

L={
 'en':dict(
   h='h',m='m',dow=['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'],
   title='Work Time Receipt',commits='commits',prompts='prompts',
   k_time='Working time',k_prompts='Prompts',k_lph='Lines / hour',k_mpp='Min / prompt',k_mpc='Min / commit',k_com='Commits',
   s_rhythm='🫀 Your rhythm',
   r_q1='Short gaps (1st quartile, Q1 = P25)',r_med='Typical gap (median, P50)',r_q3='Long gaps (3rd quartile, Q3 = P75)',
   r_iqr='Normal pace (interquartile range, IQR = Q3 − Q1)',r_p90='Rare long gaps (90th percentile, P90)',
   r_tukey='Break threshold (Tukey upper fence, Q3 + 1.5·IQR)',
   r_note='Your typical gap between prompts (median) is {med}; the middle half of your gaps (interquartile range) is {q1}–{q3}. By Tukey\'s outlier rule (Q3 + 1.5·IQR) anything above {tukey} is an outlier for you, i.e. a break. This report uses {idle} ({mode}). {pct}% of your gaps are within it (cumulative share).',
   mode_fixed='set by you',mode_auto='your own threshold, computed automatically',mode_few='default — too few prompts to compute your own',
   k_thr='Break threshold (Tukey fence)',p_sens='Sensitivity',
   bands=['quick fix / short answer','normal back-and-forth','waiting + reviewing + deciding','grey zone','probably a break','context switch'],
   s_sens='🎚️ Threshold sensitivity',sens_c=['Threshold','Gaps within (cumulative %, CDF)','Working time'],
   sens_note='How much the total moves if the break threshold changes. The result is sensitive to it, which is why the threshold comes from your own gap distribution instead of a guess.',
   s_daily='📅 Daily',c=['Date','Day','Prompts','Working time','Commits','Code lines','Lines/h'],tot='TOTAL',
   s_sum='📝 Daily commit log',
   fb_title='No Claude session logs found — fallback estimate',
   fb_note='Without session logs this is a rough estimate from gaps between commits (breaks >{b}m dropped) plus {r} min per effective added line. It tends to overestimate AI-heavy work.',
   k_est='Commit estimate',
   p_repo='Repo',p_range='Range',p_time='Working time',p_prompts='Prompts',p_commits='Commits',p_code='Effective code',p_lines='lines',
   p_rhythm='Rhythm',rh='Q1 (1st quartile) {q1} · median (P50) {med} · Q3 (3rd quartile) {q3} · IQR (interquartile range) {iqr} · P90 {p90} · Tukey upper fence (Q3+1.5·IQR) {tk}  ({n} gaps)',p_est='Commit estimate (fallback)',p_none='No prompts in range — using the commit estimate.',
   e_none='No commits or prompts found in this range.'),
 'tr':dict(
   h='s',m='d',dow=['Pazartesi','Salı','Çarşamba','Perşembe','Cuma','Cumartesi','Pazar'],
   title='Çalışma Süresi Fişi',commits='commit',prompts='prompt',
   k_time='Çalışma süresi',k_prompts='Prompt',k_lph='Satır / saat',k_mpp='Dk / prompt',k_mpc='Dk / commit',k_com='Commit',
   s_rhythm='🫀 Çalışma ritmin',
   r_q1='Kısa aralıklar (1. çeyrek, Q1 = P25)',r_med='Tipik aralık (medyan / ortanca, P50)',r_q3='Uzun aralıklar (3. çeyrek, Q3 = P75)',
   r_iqr='Normal tempo (çeyrekler arası aralık, IQR = Q3 − Q1)',r_p90='Nadir uzun aralıklar (90. yüzdelik, P90)',
   r_tukey='Mola sınırı (Tukey üst çiti, Q3 + 1,5·IQR)',
   r_note='İki prompt arasındaki tipik aralığın (medyan) {med}; aralıklarının ortadaki yarısı (çeyrekler arası aralık) {q1}–{q3}. Tukey aykırı değer kuralına göre (Q3 + 1,5·IQR) {tukey} üstü senin için aykırı değer, yani mola. Bu rapor {idle} eşiğini kullanıyor ({mode}). Aralıklarının %{pct}\'i bu eşiğin içinde (kümülatif oran).',
   mode_fixed='senin seçtiğin',mode_auto='senin ritminden otomatik hesaplandı',mode_few='varsayılan — kendi eşiğini hesaplamak için prompt az',
   k_thr='Mola sınırı (Tukey çiti)',p_sens='Duyarlılık',
   bands=['hızlı düzeltme / kısa cevap','normal etkileşim','bekleme + inceleme + karar','gri bölge','muhtemel mola','bağlam kopması'],
   s_sens='🎚️ Eşik duyarlılığı',sens_c=['Eşik','Eşik altındaki aralıklar (kümülatif %, CDF)','Çalışma süresi'],
   sens_note='Mola eşiği değişirse toplam ne kadar oynar. Sonuç eşiğe hassas; bu yüzden eşik tahminle değil, senin kendi aralık dağılımından seçiliyor.',
   s_daily='📅 Günlük',c=['Tarih','Gün','Prompt','Çalışma','Commit','Kod satırı','Satır/s'],tot='TOPLAM',
   s_sum='📝 Günlük commit özeti',
   fb_title='Claude oturum kaydı yok — yedek tahmin',
   fb_note='Oturum kaydı olmadığı için bu, commit\'ler arası süreden (>{b}dk molalar atılır) ve eklenen her etkin satıra {r} dk eklenerek yapılan kaba bir tahmin. AI ağırlıklı işte fazla gösterme eğilimindedir.',
   k_est='Commit tahmini',
   p_repo='Repo',p_range='Aralık',p_time='Çalışma süresi',p_prompts='Prompt',p_commits='Commit',p_code='Etkin kod',p_lines='satır',
   p_rhythm='Ritim',rh='Q1 (1. çeyrek) {q1} · medyan (P50) {med} · Q3 (3. çeyrek) {q3} · IQR (çeyrekler arası aralık) {iqr} · P90 {p90} · Tukey üst çiti (Q3+1,5·IQR) {tk}  ({n} aralık)',p_est='Commit tahmini (yedek)',p_none='Aralıkta prompt yok — commit tahmini kullanılıyor.',
   e_none='Bu aralıkta commit ya da prompt bulunamadı.'),
}

def default_lang():
    loc=os.environ.get('LC_ALL') or os.environ.get('LC_MESSAGES') or os.environ.get('LANG') or ''
    return 'tr' if loc.lower().startswith('tr') else 'en'

def day_of(t): return datetime.datetime.fromtimestamp(t).strftime('%Y-%m-%d')

def pctl(xs,p):
    if not xs: return 0
    k=(len(xs)-1)*p/100; f=int(k); c=min(f+1,len(xs)-1)
    return xs[f]+(xs[c]-xs[f])*(k-f)

def claude_dirs(repo):
    """Claude Code turns every non-alphanumeric character of the project path into '-'.
    Returns the repo's folder plus sessions under its .claude/worktrees."""
    enc=re.sub(r'[^A-Za-z0-9]','-',repo)
    base=os.path.expanduser('~/.claude/projects')
    return [d for d in glob.glob(os.path.join(base,enc+'*'))
            if os.path.basename(d)==enc or os.path.basename(d).startswith(enc+'--claude-worktrees-')]

def load_commits(repo,author,since,until):
    cmd=['git','-C',repo,'log','--all','--no-merges','--pretty=format:C|%at|%s','--numstat']
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

def parse_ts(o):
    t=o.get('timestamp')
    if not t: return None
    try: return datetime.datetime.fromisoformat(t.replace('Z','+00:00')).timestamp()
    except Exception: return None

def text_of(c):
    if isinstance(c,str): return c
    if isinstance(c,list): return ' '.join(x.get('text','') for x in c if isinstance(x,dict) and x.get('type')=='text')
    return ''

def load_prompts(dirs,since,until):
    """Timestamps of what YOU put in: typed messages + answers to Claude's AskUserQuestion.
    Tool results, Claude's replies, subagent traffic, compaction summaries, IDE/system
    injections and interrupt markers are not prompts."""
    recs=[]
    for d in dirs:
        for tf in glob.glob(os.path.join(d,'*.jsonl')):
            for ln in open(tf,errors='ignore'):
                try: recs.append(json.loads(ln))
                except Exception: continue
    ask_ids=set()
    for o in recs:
        if o.get('type')=='assistant':
            c=(o.get('message') or {}).get('content')
            if isinstance(c,list):
                for x in c:
                    if isinstance(x,dict) and x.get('type')=='tool_use' and x.get('name')=='AskUserQuestion':
                        ask_ids.add(x.get('id'))
    out=set()
    for o in recs:
        if o.get('type')!='user' or o.get('isSidechain') or o.get('isMeta') or o.get('isCompactSummary'): continue
        ts=parse_ts(o)
        if ts is None or not since<=day_of(ts)<=until: continue
        c=(o.get('message') or {}).get('content')
        results=[x for x in c if isinstance(x,dict) and x.get('type')=='tool_result'] if isinstance(c,list) else []
        if results:
            if any(x.get('tool_use_id') in ask_ids for x in results): out.add(ts)   # your decision
            continue                                                                 # tool output
        t=text_of(c)
        if not t.strip() or 'Request interrupted' in t or NOISE_TAG.search(t): continue
        out.add(ts)
    return sorted(out)

def main():
    ap=argparse.ArgumentParser(description='Working time from your Claude Code prompts (+ git commits for context)')
    ap.add_argument('repo',nargs='?',default='.',help='git repo to analyse (default: .)')
    ap.add_argument('--since',default='0000-00-00',help='first day YYYY-MM-DD')
    ap.add_argument('--until',default='9999-99-99',help='last day YYYY-MM-DD')
    ap.add_argument('--author',help='only commits by this author (git --author pattern)')
    ap.add_argument('--transcripts',action='append',help='Claude log folder (overrides auto-detection, repeatable)')
    ap.add_argument('--idle',default='auto',help='break threshold in minutes; default "auto" = your own Tukey threshold (Q3+1.5·IQR)')
    ap.add_argument('--lang',choices=sorted(L),default=default_lang(),help='report language (default: from $LANG, else en)')
    ap.add_argument('--name',help='project name shown in the report (default: repo folder name)')
    ap.add_argument('--out',default=os.path.expanduser('~/vibe-receipts'),help='output folder (default ~/vibe-receipts)')
    a=ap.parse_args()
    T=L[a.lang]; e=html.escape

    def hm(s):
        mm=int(round(s/60)); return f"{mm//60}{T['h']} {mm%60:02d}{T['m']}"
    def mins(x): return f"{x:.1f} {'dk' if a.lang=='tr' else 'min'}".replace('.',',' if a.lang=='tr' else '.')
    def dow(d): return T['dow'][datetime.date.fromisoformat(d).weekday()]

    repo=os.path.realpath(a.repo)
    name=a.name or os.path.basename(repo)
    try: commits=load_commits(repo,a.author,a.since,a.until)
    except subprocess.CalledProcessError: commits=[]
    dirs=a.transcripts or claude_dirs(repo)
    prompts=load_prompts(dirs,a.since,a.until)
    if not commits and not prompts: raise SystemExit(T['e_none'])

    # --- your rhythm: distribution of gaps between prompts ---
    gaps=sorted((prompts[i]-prompts[i-1])/60 for i in range(1,len(prompts)))
    med,q1,q3,p90=pctl(gaps,50),pctl(gaps,25),pctl(gaps,75),pctl(gaps,90)
    tukey=q3+1.5*(q3-q1)
    if a.idle.strip().lower()!='auto': mode,idle='fixed',float(a.idle)
    elif len(gaps)>=MIN_GAPS:          mode,idle='auto',round(tukey,1)
    else:                              mode,idle='few',float(IDLE)

    def active(thr):
        tot=0; per={}
        for i in range(1,len(prompts)):
            g=prompts[i]-prompts[i-1]
            if g<=thr*60:
                tot+=g; d=day_of(prompts[i]); per[d]=per.get(d,0)+g
        return tot,per
    work,dwork=active(idle)

    # --- commits: context (what got built) + fallback estimate ---
    dcom={};dcode={};dadd={};ddel={};dsubj={};dmeas={}
    for i,c in enumerate(commits):
        d=day_of(c['t'])
        dcom[d]=dcom.get(d,0)+1; dsubj.setdefault(d,[]).append(c['subj'])
        if i>0 and c['t']-commits[i-1]['t']<=BREAK: dmeas[d]=dmeas.get(d,0)+c['t']-commits[i-1]['t']
        for ad,de,path in c['f']:
            if ad=='-' or de=='-': continue
            ad,de=int(ad),int(de)
            dadd[d]=dadd.get(d,0)+ad; ddel[d]=ddel.get(d,0)+de
            if '=>' in path and ad==0 and de==0: continue
            dcode[d]=dcode.get(d,0)+CODE_W[kind(path)]*ad
    code=sum(dcode.values())
    dest={d:dmeas.get(d,0)+dcode.get(d,0)*CODE_RATE*60 for d in dcom}
    est=sum(dest.values())

    has_p=bool(prompts)
    total=work if has_p else est
    dtotal=dwork if has_p else dest
    dprompt={}
    for t in prompts: dprompt[day_of(t)]=dprompt.get(day_of(t),0)+1
    days=sorted(set(dcom)|set(dprompt))
    d0,d1=days[0],days[-1]
    hours=total/3600
    lph=code/hours if hours else 0
    mpp=(work/60)/len(prompts) if prompts else 0
    mpc=(total/60)/len(commits) if commits else 0

    print(f"{T['p_repo']:<15}: {repo}")
    print(f"{T['p_range']:<15}: {d0} → {d1}")
    if has_p:
        print(f"{T['p_time']:<15}: {hm(work)}   ({len(prompts)} {T['prompts']}, {len(dirs)} dir)")
        print(f"{T['k_thr']}: {mins(idle)}   ({T['mode_'+mode]})")
        print(f"{T['p_rhythm']:<15}: "+T['rh'].format(q1=mins(q1),med=mins(med),q3=mins(q3),iqr=mins(q3-q1),p90=mins(p90),tk=mins(tukey),n=len(gaps)))
        print(f"{T['p_sens']:<15}: "+' · '.join(f"{mins(t)} → {hm(active(t)[0])}" for t in sorted(set(SENS+[idle]))))
    else:
        print(T['p_none'])
        print(f"{T['p_est']:<15}: {hm(est)}")
    print(f"{T['p_commits']:<15}: {len(commits)}   ({T['p_code']} {code:.0f} {T['p_lines']})")

    # ===== HTML REPORT =====
    def bar(v,m,c):
        w=0 if not m else v/m*100
        return f'<div class="bar"><div class="barfill" style="width:{w:.1f}%;background:{c}"></div></div>'

    P=[f'<!doctype html><html lang="{a.lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(name)} · {T["title"]}</title><style>{CSS}</style></head><body><div class="wrap">']
    sub=(f'{len(prompts):,} {T["prompts"]} · ' if has_p else '')+f'{len(commits)} {T["commits"]} · {d0} → {d1}'
    P.append(f'<header><h1>🧾 {e(name)} · {T["title"]}</h1><div class="sub">{sub}</div></header>')
    if has_p:
        K=[(hm(work),T['k_time'],1),(mins(idle),T['k_thr'],0),(f'{len(prompts):,}',T['k_prompts'],0),(f'{lph:,.0f}',T['k_lph'],0),
           (mins(mpp),T['k_mpp'],0),(mins(mpc) if commits else '—',T['k_mpc'],0),(str(len(commits)),T['k_com'],0)]
    else:
        K=[(hm(est),T['k_est'],1),(f'{lph:,.0f}',T['k_lph'],0),(mins(mpc),T['k_mpc'],0),(str(len(commits)),T['k_com'],0)]
    P.append('<div class="kpis">'+''.join(f'<div class="kpi{" hero" if h else ""}"><div class="v">{v}</div><div class="l">{l}</div></div>' for v,l,h in K)+'</div>')

    if has_p and gaps:
        within=100*sum(1 for g in gaps if g<=idle)/len(gaps)
        P.append(f'<h2>{T["s_rhythm"]}</h2><div class="card">')
        P.append('<div class="stats">'+''.join(f'<div class="st{" hi" if hi else ""}"><div class="v">{mins(v)}</div><div class="l">{l}</div></div>'
                 for v,l,hi in [(q1,T['r_q1'],0),(med,T['r_med'],0),(q3,T['r_q3'],0),(q3-q1,T['r_iqr'],0),(p90,T['r_p90'],0),(tukey,T['r_tukey'],1)])+'</div>')
        cnt=[sum(1 for g in gaps if lo<=g<(hi if hi is not None else 1e18)) for lo,hi in BANDS]
        cols=['#34d399','#34d399','#34d399','#fbbf24','#f87171','#f87171']
        for (lo,hi),n,lbl,col in zip(BANDS,cnt,T['bands'],cols):
            rng=f'{lo}–{hi}' if hi is not None else f'{lo}+'
            P.append(f'<div class="scn"><div class="nm"><b>{rng}</b> · {lbl}</div>{bar(n,max(cnt),col)}<div class="vl">{100*n/len(gaps):.0f}%</div></div>')
        P.append(f'<div class="note">{e(T["r_note"].format(q1=mins(q1),q3=mins(q3),med=mins(med),tukey=mins(tukey),idle=mins(idle),mode=T["mode_"+mode],pct=f"{within:.0f}"))}</div></div>')

        P.append(f'<h2>{T["s_sens"]}</h2><div class="card"><table>')
        C=T['sens_c']; P.append(f'<tr><th>{C[0]}</th><th class="r">{C[1]}</th><th>{C[2]}</th></tr>')
        rows=[(t,)+active(t)[:1] for t in sorted(set(SENS+[idle]))]
        mxs=max(r[1] for r in rows) or 1
        for t,w in rows:
            cov=100*sum(1 for g in gaps if g<=t)/len(gaps)
            P.append(f'<tr{" class=\"sel\"" if t==idle else ""}><td>≤ {mins(t)}</td><td class="r">{cov:.0f}%</td>'
                     f'<td><div style="display:flex;align-items:center;gap:8px">{bar(w,mxs,"#a78bfa" if t==idle else "#3f4560")}<span style="width:64px;text-align:right">{hm(w)}</span></div></td></tr>')
        P.append(f'</table><div class="note">{e(T["sens_note"])}</div></div>')
    elif not has_p:
        P.append(f'<h2>⚠️ {T["fb_title"]}</h2><div class="card"><div class="note">{e(T["fb_note"].format(b=BREAK//60,r=CODE_RATE))}</div></div>')

    mx=max(dtotal.values(),default=0) or 1
    C=T['c']
    P.append(f'<h2>{T["s_daily"]}</h2><div class="card"><div class="scroll"><table>')
    P.append(f'<tr><th>{C[0]}</th><th>{C[1]}</th>'+(f'<th class="r">{C[2]}</th>' if has_p else '')+f'<th>{C[3]}</th><th class="r">{C[4]}</th><th class="r">{C[5]}</th><th class="r">{C[6]}</th></tr>')
    for d in days:
        w=dtotal.get(d,0); l=dcode.get(d,0)
        P.append(f'<tr><td>{d[5:]}</td><td>{dow(d)}</td>'+(f'<td class="r">{dprompt.get(d,0)}</td>' if has_p else '')
                 +f'<td><div style="display:flex;align-items:center;gap:8px">{bar(w,mx,"#a78bfa")}<span style="width:64px;text-align:right">{hm(w)}</span></div></td>'
                 f'<td class="r">{dcom.get(d,0)}</td><td class="r" style="color:#86efac">+{l:,.0f}</td><td class="r">{(l/(w/3600)) if w else 0:,.0f}</td></tr>')
    P.append(f'<tr class="tot"><td colspan="2">{T["tot"]}</td>'+(f'<td class="r">{len(prompts):,}</td>' if has_p else '')
             +f'<td>{hm(total)}</td><td class="r">{len(commits)}</td><td class="r">+{code:,.0f}</td><td class="r">{lph:,.0f}</td></tr>')
    P.append('</table></div></div>')

    if dsubj:
        P.append(f'<h2>{T["s_sum"]}</h2>')
        for d in sorted(dsubj):
            items=''.join(f'<li>{e(s)}</li>' for s in dsubj[d])
            P.append(f'<div class="dayblk"><h3>{d[5:]} · {dow(d)} <span class="hrs">{hm(dtotal.get(d,0))} · {dcom[d]} {T["commits"]}</span></h3><ul>{items}</ul></div>')

    P.append(f'<div class="foot">🧾 vibe-receipts · {e(name)} · {datetime.date.today()}</div></div></body></html>')

    os.makedirs(a.out,exist_ok=True)
    out=os.path.join(a.out,f'{name}-report.html')
    open(out,'w',encoding='utf-8').write('\n'.join(P))
    csvp=os.path.join(a.out,f'{name}-daily.csv')
    with open(csvp,'w',encoding='utf-8') as f:
        f.write('date,prompts,work_min,commits,effective_lines,added,deleted,commit_estimate_min\n')
        for d in days:
            f.write(f'{d},{dprompt.get(d,0)},{dwork.get(d,0)/60:.0f},{dcom.get(d,0)},{dcode.get(d,0):.0f},{dadd.get(d,0)},{ddel.get(d,0)},{dest.get(d,0)/60:.0f}\n')
    print("HTML:",out); print("CSV :",csvp)

CSS="""*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,'Segoe UI',Roboto,sans-serif;background:#0f1117;color:#e6e8ee;line-height:1.55;padding:40px 16px}
.wrap{max-width:920px;margin:0 auto}
h1{font-size:28px;font-weight:800;letter-spacing:-.5px}
h2{font-size:19px;margin:36px 0 14px;padding-bottom:8px;border-bottom:1px solid #272b36;color:#fff}
.sub{color:#8b90a0;margin-top:6px;font-size:14px}
.kpis{display:grid;grid-template-columns:1.3fr repeat(3,1fr);gap:10px;margin-top:26px}
.kpi{background:#171a23;border:1px solid #242938;border-radius:14px;padding:14px}
.kpi .v{font-size:20px;font-weight:800;color:#e6e8ee}.kpi .l{font-size:10.5px;color:#8b90a0;margin-top:4px;text-transform:uppercase;letter-spacing:.5px}
.kpi.hero{background:linear-gradient(135deg,#2a2147,#171a23);border-color:#4c3d85}.kpi.hero{grid-row:span 2;display:flex;flex-direction:column;justify-content:center}.kpi.hero .v{color:#c4b5fd;font-size:34px}.kpi .v{white-space:nowrap}
.card{background:#171a23;border:1px solid #242938;border-radius:14px;padding:22px;margin-top:14px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px;margin-bottom:16px}
.st{background:#13161f;border:1px solid #242938;border-radius:10px;padding:12px 14px}.st .v{font-size:19px;font-weight:800}.st .l{font-size:12.5px;color:#8b90a0;margin-top:2px}
.st.hi{border-color:#34d399}.st.hi .v{color:#34d399}
.scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:9px 10px;border-bottom:1px solid #242938;white-space:nowrap}
th{color:#8b90a0;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.4px}
td.r,th.r{text-align:right}tr:last-child td{border-bottom:none}
tr.sel td{color:#fff;font-weight:700;background:#1c2030}
.tot{font-weight:700;color:#fff;background:#1c2030}
.bar{background:#242938;border-radius:6px;height:20px;overflow:hidden;min-width:70px;flex:1}.barfill{height:100%;border-radius:6px}
.scn{display:flex;align-items:center;gap:12px;margin:8px 0}.scn .nm{width:260px;font-size:13px;color:#c8ccd8}.scn .vl{width:48px;text-align:right;font-weight:700;font-size:14px}
.note{font-size:12.5px;color:#8b90a0;margin-top:12px;font-style:italic}
.dayblk{background:#13161f;border:1px solid #242938;border-radius:12px;padding:14px 16px;margin-top:12px}
.dayblk h3{font-size:15px;color:#fff;display:flex;justify-content:space-between}.dayblk h3 .hrs{font-size:13px;color:#a78bfa;font-weight:700}
.dayblk ul{margin:8px 0 0 18px}.dayblk li{font-size:13.5px;color:#aeb3c2;margin:5px 0}
.foot{text-align:center;color:#5d6273;font-size:12px;margin-top:38px}
@media (max-width:600px){.scn .nm{width:150px}.kpis{grid-template-columns:1fr 1fr}.kpi.hero{grid-row:auto;grid-column:span 2}}"""

if __name__=='__main__':
    main()
