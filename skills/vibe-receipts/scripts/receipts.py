#!/usr/bin/env python3
"""vibe-receipts — how many hours did you really work on a project with Claude?

Working time = sum of the gaps between YOUR consecutive prompts in Claude Code session
logs (~/.claude/projects). A gap up to your break threshold counts as work, anything longer
is a break. By default the threshold is computed from your own gaps with Tukey's rule
(Q3 + 1.5·IQR); pass --break MIN to use a fixed one. Commits only add context (what got built). For repos with
no session logs, a rough commit-gap estimate is used as a fallback.

Usage:
  python3 receipts.py /path/to/repo
  python3 receipts.py /path/to/repo --since 2026-06-01 --until 2026-06-30
  python3 receipts.py /path/to/repo --break 20      # fixed 20-minute break threshold
  python3 receipts.py /path/to/repo --lang tr       # Türkçe rapor

Besides the HTML report and CSV it writes <repo>-receipt.png, a shareable receipt card
(rendered with a local Chrome/Chromium in headless mode; skipped if none is found).
"""
import argparse, base64, datetime, glob, html, json, os, pathlib, re, shutil, subprocess

IDLE       = 15            # minutes: fallback threshold when there are too few gaps for Tukey
MIN_GAPS   = 20            # fewer gaps than this = Tukey threshold is not reliable
CAP        = 30            # minutes: the automatic threshold never goes above this (a 30+ min gap is a break)
SENS       = [5,10,15,20,30,45,60]   # thresholds shown in the sensitivity table
BANDS      = [(0,2),(2,5),(5,15),(15,30),(30,60),(60,None)]

# Fallback commit estimate (only used when there are no session logs)
BREAK      = 150*60        # gap between commits longer than this = break
CODE_RATE  = 0.02          # minutes per effective added line

# Weights for added lines (only real code/config; docs/vendor/generated weigh 0)
CODE_W = {'code':1.0, 'config':0.4, 'arch':0.0, 'doc':0.0, 'vendor':0.0, 'gen':0.0}

# Token value: Anthropic API list prices, $ per million tokens (input, output, cache read).
# Cache writes cost 1.25x input (5-minute cache) or 2x input (1-hour cache); fast mode doubles everything.
# Responses from models not listed here are left out of the value (the receipt then shows it as "≥").
PRICES_AS_OF = '2026-09'
PRICES = {
    'claude-fable-5-1':(10,50,0.25), 'claude-mythos-5-1':(10,50,0.25), 'claude-fable-5':(10,50,1.0),
    'claude-opus-5-5':(4,20,0.20), 'claude-opus-5':(5,25,0.50), 'claude-opus-4-8':(5,25,0.50),
    'claude-opus-4-7':(5,25,0.50), 'claude-opus-4-6':(5,25,0.50),
    'claude-sonnet-5-5':(2,10,0.20), 'claude-sonnet-5':(2,10,0.20), 'claude-sonnet-4-6':(3,15,0.30),
    'claude-haiku-4-5':(1,5,0.10),
}

# Bulk-copied/moved static content — excluded. Extend for your project.
VENDOR_RE=re.compile(r'(^|/)(prototypes/|_archive/|vendor/|third_party/)|(^|/)(src/)?ui/.*\.(html|css|js)$')
GEN_RE=re.compile(r'(pnpm-lock|package-lock|yarn\.lock|poetry\.lock|Cargo\.lock|payload-types|/migrations/|\.min\.(js|css)$)')

def kind(path):
    p=path.lower()
    if VENDOR_RE.search(p): return 'vendor'
    if GEN_RE.search(p): return 'gen'
    if re.search(r'(^|/)docs?/',p): return 'doc'   # everything under docs/: notes, exports, screenshots data
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
   mode_fixed='set by you',mode_auto='your own threshold, computed automatically',mode_few='default — too few prompts to compute your own',mode_capped='your rhythm gave {tk}, capped at {cap}',
   k_thr='Break threshold (Tukey fence)',p_sens='Sensitivity',
   bands=['quick fix / short answer','normal back-and-forth','waiting + reviewing + deciding','grey zone','probably a break','context switch'],
   s_sens='🎚️ Threshold sensitivity',sens_c=['Threshold','Gaps within (cumulative %, CDF)','Working time'],
   sens_note='How much the total moves if the break threshold changes. The result is sensitive to it, which is why the threshold comes from your own gap distribution instead of a guess.',
   s_daily='📅 Daily',c=['Date','Day','Prompts','Working time','Commits','Code lines','Lines/h'],tot='TOTAL',
   s_sum='📝 Daily commit log',s_receipt='🧾 Your receipt',rc_share_note='Ready to post with the image:',
   fb_title='No Claude session logs found — fallback estimate',
   fb_note='Without session logs this is a rough estimate from gaps between commits (breaks >{b}m dropped) plus {r} min per effective added line. It tends to overestimate AI-heavy work.',
   k_est='Commit estimate',
   p_repo='Repo',p_range='Range',p_time='Working time',p_prompts='Prompts',p_commits='Commits',p_code='Effective code',p_lines='lines',
   p_rhythm='Rhythm',rh='Q1 (1st quartile) {q1} · median (P50) {med} · Q3 (3rd quartile) {q3} · IQR (interquartile range) {iqr} · P90 {p90} · Tukey upper fence (Q3+1.5·IQR) {tk}  ({n} gaps)',p_est='Commit estimate (fallback)',p_none='No prompts in range — using the commit estimate.',
   e_none='No commits or prompts found in this range.',
   g_why=dict(nogit='git is not installed, so commits are left out',norepo='No git history here, so commits are left out',none='No commits in this range'),
   g_tail='Working time comes from your prompts.',
   s_claude='🤖 Claude side',c_read='Tokens read',c_written='Tokens written',c_total='Tokens total',c_runs='Sessions (runs)',c_subs='Subagents',
   c_rows=['Input (new, not cached)','Cache write (added to the context)','Cache read (context re-read every turn)','Output (written by Claude)'],
   c_note='Claude re-reads the whole conversation on every turn, so tokens read are hundreds of times tokens written. Each response is counted once (Claude Code logs repeat it over several lines); subagents are included.',
   c_value='Token value',c_nocache='Token value without prompt cache',
   c_value_note='What these tokens would cost at Anthropic API list prices ({asof}); cache writes are 1.25x input (5-minute cache) or 2x (1-hour cache). Not what a subscription costs you.',
   c_unpriced=' {n} responses from models with no known price are left out, so the real value is higher.',
   c_model='Model mix (share of tokens written)',c_types='Subagent types',days='days',active='active days',
   rc_kind='WORK TIME RECEIPT',rc_project='PROJECT',rc_built='BUILT',rc_tokens='TOKENS',rc_agents=('AGENTS','RUNS','SUBAGENTS'),rc_model='MODEL',rc_tok=('READ','WRITTEN'),rc_active='ACTIVE DAYS',rc_days=lambda n:f"{n} DAY{'S'*(n!=1)}",rc_period='PERIOD',rc_qty='QTY',rc_item='ITEM',rc_time='TIME',
   rc_prompts='PROMPTS',rc_commits='COMMITS',rc_code='CODE LINES',rc_total='TOTAL',rc_value='TOKEN VALUE',
   rc_thr='BREAK THRESHOLD',rc_note=dict(auto='Based on your own prompt rhythm. Longer gaps are breaks, not work.',
     fixed='Set by you. Longer gaps are breaks, not work.',capped='Your rhythm gave {tk}, capped at {cap}. Longer gaps are breaks.',few='Default: too few prompts to read your rhythm. Longer gaps are breaks.'),
   rc_est='NO SESSION LOGS',rc_est_note='Rough estimate from the gaps between commits.',
   rc_unit_p='prompts',rc_unit_c='commits',rc_wk='wk of',rc_dow=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'],
   # the joke: what you said before you started; picked so the receipt's TOTAL is always more
   share='{q} {t} later{v}. 🧾 github.com/sahmett/vibe-receipts #vibereceipts',share_v=', {v} of tokens',share_t=lambda h,m:f'{h}h {m}m',
   rc_quote=[(0.5,'\u201cTwo-minute change.\u201d'),(3,'\u201cJust a quick fix.\u201d'),(None,"\u201cIt's a 2-hour project.\u201d")]),
 'tr':dict(
   h='s',m='d',dow=['Pazartesi','Salı','Çarşamba','Perşembe','Cuma','Cumartesi','Pazar'],
   title='Çalışma Süresi Fişi',commits='commit',prompts='prompt',
   k_time='Çalışma süresi',k_prompts='Prompt',k_lph='Satır / saat',k_mpp='Dk / prompt',k_mpc='Dk / commit',k_com='Commit',
   s_rhythm='🫀 Çalışma ritmin',
   r_q1='Kısa aralıklar (1. çeyrek, Q1 = P25)',r_med='Tipik aralık (medyan / ortanca, P50)',r_q3='Uzun aralıklar (3. çeyrek, Q3 = P75)',
   r_iqr='Normal tempo (çeyrekler arası aralık, IQR = Q3 − Q1)',r_p90='Nadir uzun aralıklar (90. yüzdelik, P90)',
   r_tukey='Mola sınırı (Tukey üst çiti, Q3 + 1,5·IQR)',
   r_note='İki prompt arasındaki tipik aralığın (medyan) {med}; aralıklarının ortadaki yarısı (çeyrekler arası aralık) {q1}–{q3}. Tukey aykırı değer kuralına göre (Q3 + 1,5·IQR) {tukey} üstü senin için aykırı değer, yani mola. Bu rapor {idle} eşiğini kullanıyor ({mode}). Aralıklarının %{pct}\'i bu eşiğin içinde (kümülatif oran).',
   mode_fixed='senin seçtiğin',mode_auto='senin ritminden otomatik hesaplandı',mode_few='varsayılan — kendi eşiğini hesaplamak için prompt az',mode_capped='ritminden {tk} çıktı, {cap} üst sınır uygulandı',
   k_thr='Mola sınırı (Tukey çiti)',p_sens='Duyarlılık',
   bands=['hızlı düzeltme / kısa cevap','normal etkileşim','bekleme + inceleme + karar','gri bölge','muhtemel mola','bağlam kopması'],
   s_sens='🎚️ Eşik duyarlılığı',sens_c=['Eşik','Eşik altındaki aralıklar (kümülatif %, CDF)','Çalışma süresi'],
   sens_note='Mola eşiği değişirse toplam ne kadar oynar. Sonuç eşiğe hassas; bu yüzden eşik tahminle değil, senin kendi aralık dağılımından seçiliyor.',
   s_daily='📅 Günlük',c=['Tarih','Gün','Prompt','Çalışma','Commit','Kod satırı','Satır/s'],tot='TOPLAM',
   s_sum='📝 Günlük commit özeti',s_receipt='🧾 Fişin',rc_share_note='Görselle birlikte paylaşmak için hazır metin:',
   fb_title='Claude oturum kaydı yok — yedek tahmin',
   fb_note='Oturum kaydı olmadığı için bu, commit\'ler arası süreden (>{b}dk molalar atılır) ve eklenen her etkin satıra {r} dk eklenerek yapılan kaba bir tahmin. AI ağırlıklı işte fazla gösterme eğilimindedir.',
   k_est='Commit tahmini',
   p_repo='Repo',p_range='Aralık',p_time='Çalışma süresi',p_prompts='Prompt',p_commits='Commit',p_code='Etkin kod',p_lines='satır',
   p_rhythm='Ritim',rh='Q1 (1. çeyrek) {q1} · medyan (P50) {med} · Q3 (3. çeyrek) {q3} · IQR (çeyrekler arası aralık) {iqr} · P90 {p90} · Tukey üst çiti (Q3+1,5·IQR) {tk}  ({n} aralık)',p_est='Commit tahmini (yedek)',p_none='Aralıkta prompt yok — commit tahmini kullanılıyor.',
   e_none='Bu aralıkta commit ya da prompt bulunamadı.',
   g_why=dict(nogit="git kurulu değil, commit'ler dahil edilmedi",norepo="Burada git geçmişi yok, commit'ler dahil edilmedi",none='Bu aralıkta commit yok'),
   g_tail="Çalışma süresi prompt'lardan hesaplanıyor.",
   s_claude='🤖 Claude tarafı',c_read='Okunan token',c_written='Yazılan token',c_total='Toplam token',c_runs='Oturum',c_subs='Subagent',
   c_rows=['Girdi (yeni, önbelleksiz)','Önbelleğe yazma (bağlama eklenen)','Önbellekten okuma (her turda yeniden okunan bağlam)','Çıktı (Claude\'un yazdığı)'],
   c_note='Claude her turda konuşmanın tamamını yeniden okur; bu yüzden okunan token yazılandan yüzlerce kat fazladır. Her cevap bir kez sayılır (Claude Code kayıtlarında birkaç satıra tekrarlanır); subagent\'lar dahildir.',
   c_value='Token value',c_nocache='Önbellek olmasaydı token value',
   c_value_note='Bu token\'ların Anthropic API liste fiyatıyla ({asof}) tutarı; önbelleğe yazma girdinin 1,25 katı (5 dakikalık önbellek) ya da 2 katı (1 saatlik önbellek). Abonelikle ödediğin tutar değil.',
   c_unpriced=' Fiyatı bilinmeyen modellerden {n} yanıt hesaba katılmadı; gerçek değer daha yüksek.',
   c_model='Model dağılımı (yazılan token payı)',c_types='Subagent türleri',days='gün',active='aktif gün',
   rc_kind='ÇALIŞMA SÜRESİ FİŞİ',rc_project='PROJE',rc_built='YAPILAN',rc_tokens='TOKEN',rc_agents=('AGENT','OTURUM','SUBAGENT'),rc_model='MODEL',rc_tok=('OKUNAN','YAZILAN'),rc_active='AKTİF GÜN',rc_days=lambda n:f'{n} GÜN',rc_period='DÖNEM',rc_qty='ADET',rc_item='KALEM',rc_time='SÜRE',
   rc_prompts='PROMPT',rc_commits='COMMIT',rc_code='KOD SATIRI',rc_total='TOPLAM',rc_value='TOKEN VALUE',
   rc_thr='MOLA SINIRI',rc_note=dict(auto='Kendi prompt ritmine göre. Daha uzun aralıklar mola sayılır, çalışma değil.',
     fixed='Senin seçtiğin eşik. Daha uzun aralıklar mola sayılır, çalışma değil.',capped='Ritminden {tk} çıktı, {cap} üst sınır uygulandı. Daha uzun aralıklar mola sayılır.',few='Varsayılan: ritmini okumak için prompt az. Daha uzun aralıklar mola sayılır.'),
   rc_est='OTURUM KAYDI YOK',rc_est_note="Commit'ler arası süreden kaba tahmin.",
   rc_unit_p='prompt',rc_unit_c='commit',rc_wk='hafta',rc_dow=['Pzt','Sal','Çar','Per','Cum','Cmt','Paz'],
   share='{q} {t} sonra{v}. 🧾 github.com/sahmett/vibe-receipts #vibereceipts',share_v=', {v} değerinde token',share_t=lambda h,m:f'{h} saat {m} dakika',
   rc_quote=[(0.5,'\u201cİki dakikalık iş.\u201d'),(3,'\u201cUfak bir düzeltme.\u201d'),(None,'\u201c2 saatlik iş.\u201d')]),
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
    raw=subprocess.check_output(cmd,text=True,errors='ignore',stderr=subprocess.DEVNULL)
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

def load_usage(dirs,since,until):
    """Token usage of every Claude response in range, subagents (<session>/subagents/) included;
    the main sessions, the subagents Claude started (Task/Agent tool calls) and the model mix
    (share of output tokens per model family).
    Claude Code writes one response as several lines that repeat its usage, so keep one per
    message id (max per field: output_tokens grows while the response streams). A resumed session
    copies its history into a new file, so sessions and subagent calls are counted by id.
    Also returns the token value: what these tokens cost at API list prices (see PRICES)."""
    K=('input_tokens','cache_creation_input_tokens','cache_read_input_tokens','output_tokens')
    per={}; spawned={}; sessions=set(); model={}; mid_model={}; w1h={}; fast=set()
    for d in dirs:
        for tf in glob.glob(os.path.join(d,'**','*.jsonl'),recursive=True):
            sub=f'{os.sep}subagents{os.sep}' in tf
            for ln in open(tf,errors='ignore'):
                if '"usage"' not in ln: continue
                try: o=json.loads(ln)
                except Exception: continue
                m=o.get('message')
                if o.get('type')!='assistant' or not isinstance(m,dict) or not isinstance(m.get('usage'),dict): continue
                ts=parse_ts(o)
                if ts is None or not since<=day_of(ts)<=until: continue
                mid=m.get('id') or o.get('uuid'); p=per.setdefault(mid,dict.fromkeys(K,0))
                u=m['usage']
                for k in K: p[k]=max(p[k],u.get(k) or 0)
                w1h[mid]=max(w1h.get(mid,0),(u.get('cache_creation') or {}).get('ephemeral_1h_input_tokens') or 0)
                if u.get('speed')=='fast': fast.add(mid)
                fam=re.match(r'claude-([a-z]+)',m.get('model') or '')   # claude-opus-5-5 -> opus; skips <synthetic>
                if fam: model[mid]=fam.group(1); mid_model[mid]=m['model']
                if not sub and o.get('sessionId'): sessions.add(o['sessionId'])
                if isinstance(m.get('content'),list):
                    for x in m['content']:
                        if isinstance(x,dict) and x.get('type')=='tool_use' and x.get('name') in ('Task','Agent'):
                            spawned[x.get('id')]=(x.get('input') or {}).get('subagent_type') or 'general-purpose'
    fam_out={}
    for mid,f in model.items(): fam_out[f]=fam_out.get(f,0)+per[mid]['output_tokens']
    tot=sum(fam_out.values()) or 1
    shares=split_minutes([v/tot*100*60 for v in fam_out.values()],100*60)   # whole percents that add up to 100
    mix=sorted(((f,pc) for f,pc in zip(fam_out,shares) if pc),key=lambda x:-x[1])
    types={}
    for t in spawned.values(): types[t]=types.get(t,0)+1
    return {k:sum(p[k] for p in per.values()) for k in K},len(sessions),len(spawned),mix,sorted(types.items(),key=lambda x:-x[1]),token_value(per,mid_model,w1h,fast)

def token_value(per,mid_model,w1h,fast):
    """$ value of the tokens at API list prices: per part (input, cache write, cache read, output),
    the total, what it would have been with no prompt cache, and how many responses had no known price."""
    v=dict(input=0.0,cache_write=0.0,cache_read=0.0,output=0.0,nocache=0.0,unpriced=0)
    for mid,p in per.items():
        mm=mid_model.get(mid)
        if not mm: continue                                                   # <synthetic> / no model
        k=re.sub(r'(-\d{8})?([\[@].*)?$','',mm)                              # drop date / [1m] / @version suffixes
        if k not in PRICES: v['unpriced']+=1; continue
        inp,out,rd=(x/1e6*(2 if mid in fast else 1) for x in PRICES[k])
        w1=min(w1h.get(mid,0),p['cache_creation_input_tokens']); w5=p['cache_creation_input_tokens']-w1
        v['input']+=p['input_tokens']*inp; v['cache_write']+=w5*inp*1.25+w1*inp*2
        v['cache_read']+=p['cache_read_input_tokens']*rd; v['output']+=p['output_tokens']*out
        v['nocache']+=(p['input_tokens']+p['cache_creation_input_tokens']+p['cache_read_input_tokens'])*inp+p['output_tokens']*out
    v['total']=v['input']+v['cache_write']+v['cache_read']+v['output']
    return v

def usd(x): return f'${x:,.2f}'

def short(n):
    """1234 -> 1.23K, 9_600_000 -> 9.6M, 2_454_000_000 -> 2.45B"""
    for div,suf in ((1e9,'B'),(1e6,'M'),(1e3,'K')):
        if n>=div:
            v=n/div; return (f'{v:.2f}'.rstrip('0').rstrip('.') if v<10 else f'{v:.1f}'.rstrip('0').rstrip('.') if v<100 else f'{v:.0f}')+suf
    return str(int(n))

def main():
    ap=argparse.ArgumentParser(description='Working time from your Claude Code prompts (+ git commits for context)')
    ap.add_argument('repo',nargs='?',default='.',help='folder to analyse, git repo or not (default: .)')
    ap.add_argument('--since',default='0000-00-00',help='first day YYYY-MM-DD')
    ap.add_argument('--until',default='9999-99-99',help='last day YYYY-MM-DD')
    ap.add_argument('--author',help='only commits by this author (git --author pattern)')
    ap.add_argument('--transcripts',action='append',help='Claude log folder (overrides auto-detection, repeatable)')
    ap.add_argument('--break','--idle',dest='idle',metavar='MIN',default='auto',help=f'break threshold in minutes (--idle is the old name); default "auto" = your own Tukey threshold (Q3+1.5·IQR), at most {CAP} min')
    ap.add_argument('--lang',choices=sorted(L),default=default_lang(),help='report language (default: from $LANG, else en)')
    ap.add_argument('--name',help='project name shown in the report (default: repo folder name)')
    ap.add_argument('--out',default=os.path.expanduser('~/vibe-receipts'),help='output folder (default ~/vibe-receipts)')
    ap.add_argument('--built',help='what the project is, 1-3 words (e.g. "e-commerce site"), shown on the receipt')
    ap.add_argument('--no-png',action='store_true',help='skip the receipt PNG (needs Chrome/Chromium; set CHROME=path to choose one)')
    a=ap.parse_args()
    a.out=os.path.abspath(os.path.expanduser(a.out))
    T=L[a.lang]; e=html.escape

    def hm(s):
        mm=int(round(s/60)); return f"{mm//60}{T['h']} {mm%60:02d}{T['m']}"
    def mins(x): return f"{x:.1f} {'dk' if a.lang=='tr' else 'min'}".replace('.',',' if a.lang=='tr' else '.')
    def dow(d): return T['dow'][datetime.date.fromisoformat(d).weekday()]

    repo=os.path.realpath(a.repo)
    name=a.name or os.path.basename(repo)
    try: commits=load_commits(repo,a.author,a.since,a.until)
    except subprocess.CalledProcessError: commits=[]   # not a git repo, or no commits yet
    except FileNotFoundError: commits=[]               # git is not installed
    gitst='ok' if commits else ('nogit' if not shutil.which('git') else 'norepo' if subprocess.run(['git','-C',repo,'rev-parse','--git-dir'],capture_output=True).returncode else 'none')
    gitmsg=f"{T['g_why'][gitst]}. {T['g_tail']}" if gitst!='ok' else ''
    dirs=a.transcripts or claude_dirs(repo)
    prompts=load_prompts(dirs,a.since,a.until)
    tok,runs,subagents,mix,subtypes,val=load_usage(dirs,a.since,a.until)
    vtxt=('≥ ' if val['unpriced'] else '')+usd(val['total'])                                     # token value as shown
    tread=tok['input_tokens']+tok['cache_creation_input_tokens']+tok['cache_read_input_tokens']   # context Claude processed
    twrote=tok['output_tokens']                                                                     # what Claude wrote
    if not commits and not prompts: raise SystemExit(T['e_none'])

    # --- your rhythm: distribution of gaps between prompts ---
    gaps=sorted((prompts[i]-prompts[i-1])/60 for i in range(1,len(prompts)))
    med,q1,q3,p90=pctl(gaps,50),pctl(gaps,25),pctl(gaps,75),pctl(gaps,90)
    tukey=q3+1.5*(q3-q1)
    if a.idle.strip().lower()!='auto': mode,idle='fixed',float(a.idle)
    elif len(gaps)>=MIN_GAPS:          mode,idle=('capped',float(CAP)) if tukey>CAP else ('auto',round(tukey,1))
    else:                              mode,idle='few',float(IDLE)
    modetxt=T['mode_'+mode].format(tk=mins(tukey),cap=mins(CAP))

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
    span=(datetime.date.fromisoformat(d1)-datetime.date.fromisoformat(d0)).days+1   # calendar days
    active_days=len(dprompt if has_p else dcom)                                       # days you actually worked
    hours=total/3600
    lph=code/hours if hours else 0
    mpp=(work/60)/len(prompts) if prompts else 0
    mpc=(total/60)/len(commits) if commits else 0

    print(f"{T['p_repo']:<15}: {repo}")
    print(f"{T['p_range']:<15}: {d0} → {d1}")
    if has_p:
        print(f"{T['p_time']:<15}: {hm(work)}   ({len(prompts)} {T['prompts']}, {len(dirs)} dir)")
        print(f"{T['k_thr']}: {mins(idle)}   ({modetxt})")
        print(f"{T['p_rhythm']:<15}: "+T['rh'].format(q1=mins(q1),med=mins(med),q3=mins(q3),iqr=mins(q3-q1),p90=mins(p90),tk=mins(tukey),n=len(gaps)))
        print(f"{T['p_sens']:<15}: "+' · '.join(f"{mins(t)} → {hm(active(t)[0])}" for t in sorted(set(SENS+[idle]))))
    else:
        print(T['p_none'])
        print(f"{T['p_est']:<15}: {hm(est)}")
    if commits: print(f"{T['p_commits']:<15}: {len(commits)}   ({T['p_code']} {code:.0f} {T['p_lines']})")
    else:       print(f"{T['p_commits']:<15}: {gitmsg}")
    if runs: print(f"{'Agents':<15}: {runs} runs · {subagents} subagents")
    if mix: print(f"{'Model mix':<15}: "+' · '.join(f'{f} {pc}%' for f,pc in mix)+"   (share of output tokens)")
    if tread+twrote:
        print(f"{'Tokens':<15}: {short(tread)} read · {short(twrote)} written · {short(tread+twrote)} total   "
              f"(input {short(tok['input_tokens'])} · cache write {short(tok['cache_creation_input_tokens'])} · cache read {short(tok['cache_read_input_tokens'])} · output {short(twrote)})")
    if val['total']:
        print(f"{'Token value':<15}: {vtxt}   (API list prices {PRICES_AS_OF}: input {usd(val['input'])} · cache write {usd(val['cache_write'])} · "
              f"cache read {usd(val['cache_read'])} · output {usd(val['output'])}; without cache {usd(val['nocache'])}"
              +(f"; {val['unpriced']} responses unpriced" if val['unpriced'] else '')+")")

    # ===== HTML REPORT =====
    def bar(v,m,c):
        w=0 if not m else v/m*100
        return f'<div class="bar"><div class="barfill" style="width:{w:.1f}%;background:{c}"></div></div>'

    P=[f'<!doctype html><html lang="{a.lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(name)} · {T["title"]}</title><style>{CSS}</style></head><body><div class="wrap">']
    sub=(f'<b>{e(a.built)}</b> · ' if a.built else '')+(f'{len(prompts):,} {T["prompts"]} · ' if has_p else '')+(f'{len(commits)} {T["commits"]} · ' if commits else '')+f'{d0} → {d1} · {span} {T["days"]}'+(
        f', {active_days} {T["active"]}' if active_days!=span else '')
    P.append(f'<header><h1>🧾 {e(name)} · {T["title"]}</h1><div class="sub">{sub}</div></header>')
    if has_p:
        K=[(hm(work),T['k_time'],1),(mins(idle),T['k_thr'],0),(f'{len(prompts):,}',T['k_prompts'],0)]+(
          [(f'{lph:,.0f}',T['k_lph'],0),(mins(mpp),T['k_mpp'],0),(mins(mpc),T['k_mpc'],0),(str(len(commits)),T['k_com'],0)] if commits else
          [(mins(mpp),T['k_mpp'],0)])
    else:
        K=[(hm(est),T['k_est'],1),(f'{lph:,.0f}',T['k_lph'],0),(mins(mpc),T['k_mpc'],0),(str(len(commits)),T['k_com'],0)]
    P.append('<div class="kpis">'+''.join(f'<div class="kpi{" hero" if h else ""}"{" style=\"grid-row:auto\"" if h and len(K)<=4 else ""}><div class="v">{v}</div><div class="l">{l}</div></div>' for v,l,h in K)+'</div>')
    if gitmsg: P.append(f'<div class="note">ℹ️ {e(gitmsg)}</div>')

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
        P.append(f'<div class="note">{e(T["r_note"].format(q1=mins(q1),q3=mins(q3),med=mins(med),tukey=mins(tukey),idle=mins(idle),mode=modetxt,pct=f"{within:.0f}"))}</div></div>')

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

    if tread+twrote:
        P.append(f'<h2>{T["s_claude"]}</h2><div class="card"><div class="stats">'+''.join(f'<div class="st"><div class="v">{v}</div><div class="l">{l}</div></div>'
                 for v,l in [(short(tread),T['c_read']),(short(twrote),T['c_written']),(short(tread+twrote),T['c_total']),(str(runs),T['c_runs']),(str(subagents),T['c_subs'])])+'</div>')
        vals=[tok['input_tokens'],tok['cache_creation_input_tokens'],tok['cache_read_input_tokens'],twrote]
        for lbl,v,col in zip(T['c_rows'],vals,['#8b90a0','#fbbf24','#3f4560','#a78bfa']):
            P.append(f'<div class="scn"><div class="nm">{e(lbl)}</div>{bar(v,max(vals),col)}<div class="vl">{short(v)}</div></div>')
        P.append(f'<div class="note">{e(T["c_note"])}</div>')
        if val['total']:
            P.append(f'<h3 class="h3">{T["c_value"]}</h3><div class="stats" style="margin-top:10px">'
                     f'<div class="st hi"><div class="v">{vtxt}</div><div class="l">{T["c_value"]}</div></div>'
                     f'<div class="st"><div class="v">{usd(val["nocache"])}</div><div class="l">{T["c_nocache"]}</div></div></div>')
            vv=[val['input'],val['cache_write'],val['cache_read'],val['output']]
            for lbl,v,col in zip(T['c_rows'],vv,['#8b90a0','#fbbf24','#3f4560','#a78bfa']):
                P.append(f'<div class="scn"><div class="nm">{e(lbl)}</div>{bar(v,max(vv),col)}<div class="vl" style="width:84px">{usd(v)}</div></div>')
            P.append(f'<div class="note">{e(T["c_value_note"].format(asof=PRICES_AS_OF)+(T["c_unpriced"].format(n=val["unpriced"]) if val["unpriced"] else ""))}</div>')
        if mix:
            P.append(f'<h3 class="h3">{T["c_model"]}</h3>'+''.join(f'<div class="scn"><div class="nm"><b>{f.capitalize()}</b></div>{bar(pc,100,"#a78bfa")}<div class="vl">{pc}%</div></div>' for f,pc in mix))
        if subtypes:
            P.append(f'<h3 class="h3">{T["c_types"]}</h3>'+''.join(f'<div class="scn"><div class="nm">{e(t)}</div>{bar(n,subtypes[0][1],"#34d399")}<div class="vl">{n}</div></div>' for t,n in subtypes))
        P.append('</div>')

    mx=max(dtotal.values(),default=0) or 1
    C=T['c']
    P.append(f'<h2>{T["s_daily"]}</h2><div class="card"><div class="scroll"><table>')
    P.append(f'<tr><th>{C[0]}</th><th>{C[1]}</th>'+(f'<th class="r">{C[2]}</th>' if has_p else '')+f'<th>{C[3]}</th>'+(f'<th class="r">{C[4]}</th><th class="r">{C[5]}</th><th class="r">{C[6]}</th>' if commits else '')+'</tr>')
    for d in days:
        w=dtotal.get(d,0); l=dcode.get(d,0)
        P.append(f'<tr><td>{d[5:]}</td><td>{dow(d)}</td>'+(f'<td class="r">{dprompt.get(d,0)}</td>' if has_p else '')
                 +f'<td><div style="display:flex;align-items:center;gap:8px">{bar(w,mx,"#a78bfa")}<span style="width:64px;text-align:right">{hm(w)}</span></div></td>'
                 +(f'<td class="r">{dcom.get(d,0)}</td><td class="r" style="color:#86efac">+{l:,.0f}</td><td class="r">{(l/(w/3600)) if w else 0:,.0f}</td>' if commits else '')+'</tr>')
    P.append(f'<tr class="tot"><td colspan="2">{T["tot"]}</td>'+(f'<td class="r">{len(prompts):,}</td>' if has_p else '')
             +f'<td>{hm(total)}</td>'+(f'<td class="r">{len(commits)}</td><td class="r">+{code:,.0f}</td><td class="r">{lph:,.0f}</td>' if commits else '')+'</tr>')
    P.append('</table></div></div>')

    if dsubj:
        P.append(f'<h2>{T["s_sum"]}</h2>')
        for d in sorted(dsubj):
            items=''.join(f'<li>{e(s)}</li>' for s in dsubj[d])
            P.append(f'<div class="dayblk"><h3>{d[5:]} · {dow(d)} <span class="hrs">{hm(dtotal.get(d,0))} · {dcom[d]} {T["commits"]}</span></h3><ul>{items}</ul></div>')

    P.append(f'<div class="foot">🧾 vibe-receipts · {e(name)} · {datetime.date.today()}</div></div></body></html>')

    # ===== SHARE CARD: <repo>-receipt.png (rendered first so the report can show it) =====
    os.makedirs(a.out,exist_ok=True)
    # Line items: one per day; per week or per month when there are too many days for a receipt.
    qty=dprompt if has_p else dcom
    if len(days)<=7: key=lambda d:d; label=lambda k:f"{T['rc_dow'][datetime.date.fromisoformat(k).weekday()]} {k[5:]}"
    else:
        def wk(d): x=datetime.date.fromisoformat(d); return (x-datetime.timedelta(days=x.weekday())).isoformat()
        if len({wk(d) for d in days})<=7: key=wk; label=lambda k:f"{T['rc_wk']} {k[5:]}"
        else: key=lambda d:d[:7]; label=lambda k:k
    groups={}
    for d in days:
        g=groups.setdefault(key(d),[0,0]); g[0]+=qty.get(d,0); g[1]+=dtotal.get(d,0)
    groups={k:g for k,g in groups.items() if g[0] or g[1]}   # commit-only days/months have no prompts and no time: no line
    unit=T['rc_unit_p'] if has_p else T['rc_unit_c']
    mins_split=split_minutes([v[1] for v in groups.values()],total)
    items=[(q,f"{unit} · {label(k)}",f"{m//60}{T['h']} {m%60:02d}{T['m']}") for (k,(q,_)),m in zip(groups.items(),mins_split)]
    # Claude's side (what went in), a blank line, then what came out
    spent=([(T['rc_prompts'],f'{len(prompts):,}')] if has_p else [])+(
           [(T['rc_agents'][0],f"{runs} {T['rc_agents'][1]} · {subagents} {T['rc_agents'][2]}")] if runs else [])+(
           [(T['rc_tokens'],' · '.join(f'{short(v)} {l}' for v,l in zip((tread,twrote),T['rc_tok'])))] if tread+twrote else [])+(
           [(T['rc_model'],' · '.join(f'{f.upper()} {pc}%' for f,pc in mix[:3]))] if mix else [])
    made=[(T['rc_commits'],str(len(commits))),(T['rc_code'],f'+{code:,.0f}')] if commits else []   # no git: the receipt just leaves commits out
    stats=spent+([None] if spent and made else [])+made
    thr=(T['rc_thr'],mins(idle),T['rc_note'][mode].format(tk=mins(tukey),cap=mins(CAP))) if has_p else (T['rc_est'],'',T['rc_est_note'])
    period=(d0 if d0==d1 else f"{d0} → {d1[5:] if d0[:4]==d1[:4] else d1}")+f" · {T['rc_days'](span)}"
    quote=next(q for lim,q in T['rc_quote'] if lim is None or hours<lim)
    value=(T['rc_value'],vtxt) if val['total'] else None
    card,H=receipt_html(T,a.lang,name,a.built,period,span,active_days,d1,items,stats,hm(total),value,thr)
    cardp=os.path.join(a.out,f'{name}-receipt.html')
    open(cardp,'w',encoding='utf-8').write(card)
    pngp=os.path.join(a.out,f'{name}-receipt.png')
    if a.no_png: pass
    elif render_png(cardp,pngp,CARD_W,H): print("PNG :",pngp)
    else: print(f"PNG : skipped, no Chrome/Chromium found (set CHROME=/path/to/chrome). Card HTML: {cardp}")
    m=int(round(total/60))   # ready-to-post text to go with the PNG
    share=T['share'].format(q=quote,t=T['share_t'](m//60,m%60),v=T['share_v'].format(v=vtxt) if val['total'] else '')

    # the card goes at the end of the report, embedded so the HTML still works on its own
    if not a.no_png and os.path.exists(pngp):
        b64=base64.b64encode(open(pngp,'rb').read()).decode()
        P.insert(-1,f'<h2>{T["s_receipt"]}</h2><div class="card rcpt"><img src="data:image/png;base64,{b64}" alt="{e(name)} receipt">'
                    f'<div class="note">{T["rc_share_note"]}</div><div class="share">{e(share)}</div></div>')

    out=os.path.join(a.out,f'{name}-report.html')
    open(out,'w',encoding='utf-8').write('\n'.join(P))
    csvp=os.path.join(a.out,f'{name}-daily.csv')
    with open(csvp,'w',encoding='utf-8') as f:
        f.write('date,prompts,work_min,commits,effective_lines,added,deleted,commit_estimate_min\n')
        for d in days:
            f.write(f'{d},{dprompt.get(d,0)},{dwork.get(d,0)/60:.0f},{dcom.get(d,0)},{dcode.get(d,0):.0f},{dadd.get(d,0)},{ddel.get(d,0)},{dest.get(d,0)/60:.0f}\n')
    print("HTML:",out); print("CSV :",csvp)
    print("Share:",share)

def split_minutes(secs,total):
    """Round each item to whole minutes so the items add up to the rounded total (largest remainder)."""
    raw=[s/60 for s in secs]; fl=[int(r) for r in raw]
    for i in sorted(range(len(raw)),key=lambda i:fl[i]-raw[i])[:int(round(total/60))-sum(fl)]: fl[i]+=1
    return fl

def receipt_html(T,lang,name,built,period,span,active_days,d1,items,stats,total,value,thr):
    """The share card: a thermal-paper receipt, straight, on a dark card. Returns (html, height)."""
    e=html.escape
    def up(x): return (x.replace('i','İ').replace('ı','I') if lang=='tr' else x).upper()   # Turkish dotted İ
    rows=''.join(f'<span>{q:,}</span><span>{e(l)}</span><span class="r">{t}</span>' for q,l,t in items)
    srows=''.join('<div class="sp"></div>' if r is None else f'<div class="row"><span>{e(r[0])}</span><span>{r[1]}</span></div>' for r in stats)
    H=2*CARD_PAD+804+24*(len(stats)-4)+26*len(items)+24*bool(built)+46*bool(value)+8   # card padding + receipt body + item/BUILT/value rows + slack
    return (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><title>{e(name)} · vibe receipt</title>'
      '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;800&display=swap">'
      f'<style>{RCSS}</style></head><body><div class="card" style="height:{H}px">'
      '<div class="rc"><div class="tear t"></div><div class="paper">'
      f'<div class="hd"><div class="t">VIBE RECEIPTS</div><div class="mute">github.com/sahmett/vibe-receipts</div><div class="mute ls">{T["rc_kind"]}</div></div>'
      '<div class="hr"></div>'
      f'<div class="row"><span>{T["rc_project"]}</span><span class="nm">{e(name)}</span></div>'
      +(f'<div class="row"><span>{T["rc_built"]}</span><span class="nm">{e(up(built))}</span></div>' if built else '')+
      f'<div class="row"><span>{T["rc_period"]}</span><span>{period}</span></div>'
      +(f'<div class="row"><span>{T["rc_active"]}</span><span>{active_days}</span></div>' if active_days!=span else '')+
      '<div class="hr"></div>'
      f'<div class="items"><span class="h">{T["rc_qty"]}</span><span class="h">{T["rc_item"]}</span><span class="h r">{T["rc_time"]}</span>{rows}</div>'
      f'<div class="hr"></div>{srows}<div class="hr2"></div>'
      +(f'<div class="val"><span>{value[0]}</span><span>{e(value[1])}</span></div>' if value else '')+   # the wow metric, mid size
      f'<div class="tot{" big" if value else ""}"><span>{T["rc_total"]}</span><span>{total}</span></div>'  # the hero: time

      '<div class="hr"></div>'
      f'<div class="row thr"><span>{thr[0]}</span><b>{e(thr[1])}</b></div>'+(f'<div class="mute">{e(thr[2])}</div>' if thr[2] else '')+
      '<div class="ft"><div class="s">* SHOW THE RECEIPTS *</div><div class="bc"></div>'
      f'<div class="mute bn">{e(up(name))} · {d1}</div><div class="ty">THANK YOU FOR VIBING</div></div>'
      '</div><div class="tear b"></div></div></div></body></html>'),H

def find_chrome():
    if os.environ.get('CHROME'): return os.environ['CHROME']
    for p in ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome','/Applications/Chromium.app/Contents/MacOS/Chromium',
              '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge','/Applications/Brave Browser.app/Contents/MacOS/Brave Browser']:
        if os.path.exists(p): return p
    for n in ['google-chrome','google-chrome-stable','chromium','chromium-browser','microsoft-edge','brave-browser']:
        if shutil.which(n): return shutil.which(n)

def render_png(src,dst,w,h):
    """Screenshot the card with headless Chrome at 2x. Returns True if the PNG was written."""
    chrome=find_chrome()
    if not chrome: return False
    if os.path.exists(dst): os.remove(dst)
    try:
        subprocess.run([chrome,'--headless','--disable-gpu','--hide-scrollbars','--no-sandbox','--force-device-scale-factor=2',
                        f'--window-size={w},{h}','--virtual-time-budget=5000',f'--screenshot={dst}',pathlib.Path(src).as_uri()],
                       capture_output=True,timeout=120)
    except (OSError,subprocess.SubprocessError): return False
    return os.path.exists(dst)

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
.h3{font-size:14px;color:#fff;margin:22px 0 4px}
.note{font-size:12.5px;color:#8b90a0;margin-top:12px;font-style:italic}
.dayblk{background:#13161f;border:1px solid #242938;border-radius:12px;padding:14px 16px;margin-top:12px}
.dayblk h3{font-size:15px;color:#fff;display:flex;justify-content:space-between}.dayblk h3 .hrs{font-size:13px;color:#a78bfa;font-weight:700}
.dayblk ul{margin:8px 0 0 18px}.dayblk li{font-size:13.5px;color:#aeb3c2;margin:5px 0}
.foot{text-align:center;color:#5d6273;font-size:12px;margin-top:38px}
.rcpt{text-align:center}.rcpt img{width:100%;max-width:440px;border-radius:12px;display:block;margin:0 auto}
.share{margin:8px auto 0;max-width:640px;background:#13161f;border:1px solid #242938;border-radius:10px;padding:10px 14px;font-size:13.5px;color:#c8ccd8;user-select:all}
@media (max-width:600px){.scn .nm{width:150px}.kpis{grid-template-columns:1fr 1fr}.kpi.hero{grid-row:auto;grid-column:span 2}}"""

PAPER,INK='#F3F0E8','#1d1c1a'
CARD_W,CARD_PAD=600,40   # the share card: just the receipt, straight, on a dark background
RCSS=f"""*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0e0f14;color:#ECEAF2;font-family:'JetBrains Mono',ui-monospace,Menlo,Consolas,monospace;font-variant-numeric:tabular-nums}}
.card{{width:{CARD_W}px;padding:{CARD_PAD}px;display:flex;flex-direction:column;align-items:center;justify-content:center;overflow:hidden}}
.rc{{width:520px;filter:drop-shadow(0 30px 40px rgba(0,0,0,.55)) drop-shadow(0 4px 8px rgba(0,0,0,.4));color:{INK}}}
.tear{{height:10px;background-size:20px 20px;background-repeat:repeat-x}}
.tear.t{{background-image:linear-gradient(45deg,{PAPER} 50%,transparent 50%),linear-gradient(-45deg,{PAPER} 50%,transparent 50%);background-position:0 0}}
.tear.b{{background-image:linear-gradient(135deg,{PAPER} 50%,transparent 50%),linear-gradient(-135deg,{PAPER} 50%,transparent 50%);background-position:0 100%}}
.paper{{background:{PAPER};padding:28px 36px 32px;font-size:15px;line-height:24px}}
.hd{{text-align:center}}.hd .t{{font-size:26px;line-height:32px;font-weight:800;letter-spacing:5px}}.hd .mute{{margin-top:2px}}
.mute{{font-size:12px;line-height:18px;color:#6b665d}}.ls{{letter-spacing:2px}}
.hr{{border-top:2px dashed #9b958a;margin:16px 0}}.hr2{{border-top:4px double {INK};margin:16px 0}}
.row{{display:flex;justify-content:space-between;gap:16px;white-space:nowrap}}
.row .nm{{font-weight:600;overflow:hidden;text-overflow:ellipsis;min-width:0}}
.items{{display:grid;grid-template-columns:56px minmax(0,1fr) auto;row-gap:2px;white-space:nowrap}}
.items span{{overflow:hidden;text-overflow:ellipsis}}.items .h{{font-size:11px;color:#6b665d;letter-spacing:1.5px}}.items .r{{text-align:right}}
.tot{{display:flex;justify-content:space-between;align-items:baseline}}
.tot span:first-child{{font-size:22px;font-weight:800;letter-spacing:3px}}.tot span:last-child{{font-size:40px;line-height:48px;font-weight:800;letter-spacing:-1px}}
.tot.big span:last-child{{font-size:46px;line-height:54px}}
.val{{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px}}
.val span:first-child{{font-size:16px;font-weight:800;letter-spacing:2px}}.val span:last-child{{font-size:28px;line-height:34px;font-weight:800}}
.thr{{font-size:13px;line-height:20px}}.sp{{height:12px}}
.ft{{padding-top:24px;display:flex;flex-direction:column;align-items:center;gap:10px;text-align:center}}
.ft .s{{font-size:16px;line-height:24px;font-weight:800;letter-spacing:3px}}
.bc{{width:300px;height:56px;background:repeating-linear-gradient(90deg,{INK} 0 3px,transparent 3px 5px,{INK} 5px 6px,transparent 6px 9px,{INK} 9px 13px,transparent 13px 15px,{INK} 15px 16px,transparent 16px 20px,{INK} 20px 22px,transparent 22px 23px)}}
.ft .bn{{font-size:11px;line-height:14px;letter-spacing:3px;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.ft .ty{{font-size:12px;line-height:18px;letter-spacing:2px}}"""

if __name__=='__main__':
    main()
