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
import argparse, base64, datetime, glob, html, http.server, json, os, pathlib, re, shutil, subprocess, tempfile, threading, zlib

IDLE       = 15            # minutes: fallback threshold when there are too few gaps for Tukey
MIN_GAPS   = 20            # fewer gaps than this = Tukey threshold is not reliable
SITE_URL   = 'https://slipt-phi.vercel.app'   # --link: the public site opens a receipt carried in the link
CAP        = 30            # minutes: the automatic threshold never goes above this (a 30+ min gap is a break)
SENS       = [5,10,15,20,30,45,60]   # thresholds shown in the sensitivity table
BANDS      = [(0,2),(2,5),(5,15),(15,30),(30,60),(60,None)]

# Commit-session estimate (only used when there are no session logs). One author's commits less than
# SESSION_GAP apart form a session; each counts SESSION_MIN + SESSION_SPAN x its length. Fitted on 112 days
# of Claude-assisted solo work in 7 repos; on a repo left out of the fit it was off by 15% on average.
SESSION_GAP  = 60*60       # seconds
SESSION_MIN  = 48          # minutes per session
SESSION_SPAN = 0.05        # share of the first-to-last-commit time

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
   fb_title='No Claude session logs — estimated from commits',
   fb_note='Estimated from your commit sessions.',
   k_est='Commit estimate',
   p_repo='Repo',p_range='Range',p_time='Working time',p_prompts='Prompts',p_commits='Commits',p_code='Effective code',p_lines='lines',
   p_rhythm='Rhythm',rh='Q1 (1st quartile) {q1} · median (P50) {med} · Q3 (3rd quartile) {q3} · IQR (interquartile range) {iqr} · P90 {p90} · Tukey upper fence (Q3+1.5·IQR) {tk}  ({n} gaps)',p_est='Commit estimate (fallback)',p_none='No prompts in range — using the commit estimate.',
   e_none='No commits or prompts found in this range.',
   p_left_out='from your prompts; {n} older/newer commits left out, use --since/--until to include them',
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
   rc_est='NO SESSION LOGS',rc_est_note='Estimated from your commit sessions.',
   rc_unit_p='prompts',rc_unit_c='commits',rc_wk='wk of',rc_q='Q',rc_dow=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'],
   # the joke: what you said before you started; picked so the receipt's TOTAL is always more
   share='{q} {t} later{v}. 🧾 github.com/sahmett/vibe-receipts #vibereceipts',share_v=', {v} of tokens',share_t=lambda h,m:f'{h}h {m}m',
   rc_quote=[(0.5,'\u201cTwo-minute change.\u201d'),(3,'\u201cJust a quick fix.\u201d'),(None,"\u201cIt's a 2-hour project.\u201d")],
   vid_later='{t} later.',vid_cta='Get your own receipt',
   b_none='No receipts archived yet: run receipts.py on a project first, then --board.'),
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
   fb_title="Claude oturum kaydı yok — commit'lerden tahmin",
   fb_note="Commit oturumlarından tahmin.",
   k_est='Commit tahmini',
   p_repo='Repo',p_range='Aralık',p_time='Çalışma süresi',p_prompts='Prompt',p_commits='Commit',p_code='Etkin kod',p_lines='satır',
   p_rhythm='Ritim',rh='Q1 (1. çeyrek) {q1} · medyan (P50) {med} · Q3 (3. çeyrek) {q3} · IQR (çeyrekler arası aralık) {iqr} · P90 {p90} · Tukey üst çiti (Q3+1,5·IQR) {tk}  ({n} aralık)',p_est='Commit tahmini (yedek)',p_none='Aralıkta prompt yok — commit tahmini kullanılıyor.',
   e_none='Bu aralıkta commit ya da prompt bulunamadı.',
   p_left_out="prompt'larından alındı; dışında kalan {n} commit dahil edilmedi, eklemek için --since/--until kullan",
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
   rc_est='OTURUM KAYDI YOK',rc_est_note="Commit oturumlarından tahmin.",
   rc_unit_p='prompt',rc_unit_c='commit',rc_wk='hafta',rc_q='Ç',rc_dow=['Pzt','Sal','Çar','Per','Cum','Cmt','Paz'],
   share='{q} {t} sonra{v}. 🧾 github.com/sahmett/vibe-receipts #vibereceipts',share_v=', {v} değerinde token',share_t=lambda h,m:f'{h} saat {m} dakika',
   rc_quote=[(0.5,'\u201cİki dakikalık iş.\u201d'),(3,'\u201cUfak bir düzeltme.\u201d'),(None,'\u201c2 saatlik iş.\u201d')],
   vid_later='{t} sonra.',vid_cta='Kendi fişini çıkar',
   b_none="Arşivde henüz fiş yok: önce receipts.py'yi bir projede çalıştır, sonra --board."),
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
    cmd=['git','-C',repo,'log','--all','--no-merges','--pretty=format:C|%at|%an|%s','--numstat']
    if author: cmd.append(f'--author={author}')
    raw=subprocess.check_output(cmd,text=True,errors='ignore',stderr=subprocess.DEVNULL)
    commits=[];cur=None
    for ln in raw.splitlines():
        if ln.startswith('C|'):
            if cur: commits.append(cur)
            _,at,an,subj=ln.split('|',3); cur={'t':int(at),'a':an,'subj':subj,'f':[]}
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
    ap.add_argument('repo',nargs='?',help='folder to analyse, git repo or not (default: .; leave it out with --board to only rebuild the board)')
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
    ap.add_argument('--video',action='store_true',help='also make <name>-receipt.mp4: the receipt printing out of a thermal printer, 1080x1920 for Reels/TikTok/Shorts (needs Chrome; ffmpeg optional)')
    ap.add_argument('--board',action='store_true',help='also rebuild board.html: every archived receipt on one page, a printer view and a status board')
    ap.add_argument('--client',help='client this receipt is for, shown on the board (kept for later runs of the same range)')
    ap.add_argument('--status',choices=['due','paid','personal'],help='board column for this receipt (default: due with a client, else personal)')
    ap.add_argument('--link',action='store_true',help=f'also print a link that opens this receipt on {SITE_URL}: the receipt rides in the #part, which is never sent to the server (no client, no status)')
    ap.add_argument('--share',action='store_true',help=f'also print a link to this receipt on {SITE_URL} whose preview shows the receipt: the server reads it from the link to draw the preview, and stores nothing (no client, no status)')
    a=ap.parse_args()
    a.out=os.path.abspath(os.path.expanduser(a.out))
    T=L[a.lang]; e=html.escape
    if a.board and a.repo is None:   # just the board, from the receipts already archived
        print("Board:",build_board(a.out,a.lang)); return
    a.repo=a.repo or '.'

    def hm(s):
        mm=int(round(s/60)); return f"{mm//60}{T['h']} {mm%60:02d}{T['m']}"
    def mins(x): return f"{x:.1f} {'dk' if a.lang=='tr' else 'min'}".replace('.',',' if a.lang=='tr' else '.')
    def dow(d): return T['dow'][datetime.date.fromisoformat(d).weekday()]

    repo=os.path.realpath(a.repo)
    name=a.name or os.path.basename(repo)
    dirs=a.transcripts or claude_dirs(repo)
    prompts=load_prompts(dirs,a.since,a.until)
    try: commits=load_commits(repo,a.author,a.since,a.until)
    except subprocess.CalledProcessError: commits=[]   # not a git repo, or no commits yet
    except FileNotFoundError: commits=[]               # git is not installed
    # No range given: the prompts set it, so the receipt's period, commits and lines cover the same days as the hours
    left_out=0
    if prompts and a.since=='0000-00-00' and a.until=='9999-99-99':
        p0,p1=day_of(prompts[0]),day_of(prompts[-1])
        kept=[c for c in commits if p0<=day_of(c['t'])<=p1]; left_out=len(commits)-len(kept); commits=kept
    gitst='ok' if commits else ('nogit' if not shutil.which('git') else 'norepo' if subprocess.run(['git','-C',repo,'rev-parse','--git-dir'],capture_output=True).returncode else 'none')
    gitmsg=f"{T['g_why'][gitst]}. {T['g_tail']}" if gitst!='ok' else ''
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
    dcom={};dcode={};dadd={};ddel={};dsubj={}
    for c in commits:
        d=day_of(c['t'])
        dcom[d]=dcom.get(d,0)+1; dsubj.setdefault(d,[]).append(c['subj'])
        for ad,de,path in c['f']:
            if ad=='-' or de=='-': continue
            ad,de=int(ad),int(de)
            dadd[d]=dadd.get(d,0)+ad; ddel[d]=ddel.get(d,0)+de
            if '=>' in path and ad==0 and de==0: continue
            dcode[d]=dcode.get(d,0)+CODE_W[kind(path)]*ad
    code=sum(dcode.values())
    dest={}   # commit-session estimate per day (see SESSION_*), per author so co-authors do not merge
    for au in {c['a'] for c in commits}:
        ts=[c['t'] for c in commits if c['a']==au]; ses=[]
        for prev,t in zip([None]+ts,ts):
            if prev is None or t-prev>SESSION_GAP: ses.append([])
            ses[-1].append(t)
        for se in ses:   # a session past midnight is shared out over its commits' days
            for t in se: d=day_of(t); dest[d]=dest.get(d,0)+(SESSION_MIN*60+SESSION_SPAN*(se[-1]-se[0]))/len(se)
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
    print(f"{T['p_range']:<15}: {d0} → {d1}"+(f"   ({T['p_left_out'].format(n=left_out)})" if left_out else ''))
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
    span1=' style="grid-row:auto"' if len(K)<=4 else ''   # hero spans two rows only when there are two rows
    P.append('<div class="kpis">'+''.join(f'<div class="kpi{" hero" if h else ""}"{span1 if h else ""}><div class="v">{v}</div><div class="l">{l}</div></div>' for v,l,h in K)+'</div>')
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
            sel=' class="sel"' if t==idle else ''
            P.append(f'<tr{sel}><td>≤ {mins(t)}</td><td class="r">{cov:.0f}%</td>'
                     f'<td><div style="display:flex;align-items:center;gap:8px">{bar(w,mxs,"#a78bfa" if t==idle else "#3f4560")}<span style="width:64px;text-align:right">{hm(w)}</span></div></td></tr>')
        P.append(f'</table><div class="note">{e(T["sens_note"])}</div></div>')
    elif not has_p:
        P.append(f'<h2>⚠️ {T["fb_title"]}</h2><div class="card"><div class="note">{e(T["fb_note"])}</div></div>')

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
    # Line items: one per day; per week, month, quarter or year when there are too many for a receipt (max ~12 lines).
    qty=dprompt if has_p else dcom
    if len(days)<=7: key=lambda d:d; label=lambda k:f"{T['rc_dow'][datetime.date.fromisoformat(k).weekday()]} {k[5:]}"
    else:
        def wk(d): x=datetime.date.fromisoformat(d); return (x-datetime.timedelta(days=x.weekday())).isoformat()
        def qtr(d): return f"{d[:4]}-{(int(d[5:7])-1)//3+1}"
        if len({wk(d) for d in days})<=7: key=wk; label=lambda k:f"{T['rc_wk']} {k[5:]}"
        elif len({d[:7] for d in days})<=12: key=lambda d:d[:7]; label=lambda k:k
        elif len({qtr(d) for d in days})<=12: key=qtr; label=lambda k:f"{k[:4]} {T['rc_q']}{k[5:]}"
        else: key=lambda d:d[:4]; label=lambda k:k
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
    rargs=(T,a.lang,name,a.built,period,span,active_days,d1,items,stats,hm(total),value,thr)
    card,H=receipt_html(*rargs)
    cardp=os.path.join(a.out,f'{name}-receipt.html')
    open(cardp,'w',encoding='utf-8').write(card)
    pngp=os.path.join(a.out,f'{name}-receipt.png')
    if a.no_png: pass
    elif render_png(cardp,pngp,CARD_W,H): print("PNG :",pngp)
    else: print(f"PNG : skipped, no Chrome/Chromium found (set CHROME=/path/to/chrome). Card HTML: {cardp}")
    m=int(round(total/60))   # ready-to-post text to go with the PNG
    share=T['share'].format(q=quote,t=T['share_t'](m//60,m%60),v=T['share_v'].format(v=vtxt) if val['total'] else '')
    if a.video:   # the receipt alone, transparent, at 3x, then the printer clip around it
        tmp=tempfile.mkdtemp(prefix='vibe-receipts-')
        try:
            paperh,PH=receipt_html(*rargs,bare=True)
            open(os.path.join(tmp,'paper.html'),'w',encoding='utf-8').write(paperh)
            ok=render_png(os.path.join(tmp,'paper.html'),os.path.join(tmp,'paper.png'),520,PH,scale=3,transparent=True)
            vid=ok and render_video(os.path.join(tmp,'paper.png'),os.path.join(a.out,f'{name}-receipt.mp4'),
                dict(quote=quote,later=T['vid_later'].format(t=T['share_t'](m//60,m%60)),cta=T['vid_cta'],
                     url='github.com/sahmett/vibe-receipts',tag='#vibereceipts'))
        finally: shutil.rmtree(tmp,ignore_errors=True)
        if vid: print("MP4 :",vid)
        else:   print("MP4 : skipped, no Chrome/Chromium found or the recording failed (set CHROME=/path/to/chrome)")

    # every run keeps its receipt as data, one file per project and range: archive/<name>_<from>_<to>.json.
    # A rerun of the same range replaces it, keeping the client and status unless they are given again.
    arch=os.path.join(a.out,'archive'); os.makedirs(arch,exist_ok=True)
    rkey=re.sub(r'[^A-Za-z0-9._-]','-',name)+f'_{d0}_{d1}'
    archp=os.path.join(arch,rkey+'.json')
    try: old=json.load(open(archp,encoding='utf-8'))
    except (OSError,ValueError): old={}
    client=(a.client if a.client is not None else old.get('client')) or None
    rec=dict(key=rkey,name=name,built=a.built,period=period,active=active_days if active_days!=span else None,start=d0,end=d1,
             items=[[q,l,mm] for (q,l,_),mm in zip(items,mins_split)],min=m,prompts=len(prompts),commits=len(commits),estimate=not has_p,
             stats=stats,value=round(val['total'],2) if val['total'] else None,value_text=vtxt if val['total'] else None,thr=list(thr),
             client=client,status=a.status or old.get('status') or ('due' if client else 'personal'),
             lang=a.lang,made=datetime.datetime.now().isoformat(timespec='seconds'),
             L=dict(kind=T['rc_kind'],project=T['rc_project'],built=T['rc_built'],period=T['rc_period'],active=T['rc_active'],qty=T['rc_qty'],
                    item=T['rc_item'],time=T['rc_time'],value=T['rc_value'],total=T['rc_total'],h=T['h'],m=T['m']))
    with open(archp,'w',encoding='utf-8') as f: json.dump(rec,f,ensure_ascii=False,indent=1)

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
    print("HTML:",out); print("CSV :",csvp); print("JSON:",archp)
    if a.board: print("Board:",build_board(a.out,a.lang))
    if a.link: print("Link:",share_link(rec))
    if a.share: print("Share link:",share_link(rec,preview=True))
    print("Share:",share)

def share_link(rec,preview=False):
    """A link to this receipt on the public site: the receipt (its numbers and labels, never the client or the
    board status), compressed. By default it goes after #, which browsers keep to themselves: no server sees it.
    preview=True puts it in the path, /r/<receipt>, so the site can draw the link's preview card from it; the
    site stores nothing, the link is the receipt."""
    keep={k:v for k,v in rec.items() if k not in ('client','status','key')}
    c=zlib.compressobj(9,zlib.DEFLATED,-15)   # raw deflate: the page reads it with DecompressionStream("deflate-raw")
    z=c.compress(json.dumps(keep,ensure_ascii=False,separators=(',',':')).encode())+c.flush()
    d=base64.urlsafe_b64encode(z).decode().rstrip('=')
    return f"{SITE_URL}/r/{d}" if preview else f"{SITE_URL}/#r={d}"

def build_board(out,lang):
    """Every archived receipt on one page, <out>/board.html: the printer view (the newest receipt printing out
    of the isometric printer) and the board (columns by status, the full receipt opening from its card). Statuses
    changed on the page are kept in that browser. Newest receipts first."""
    recs=[]
    for p in glob.glob(os.path.join(out,'archive','*.json')):
        try: recs.append(json.load(open(p,encoding='utf-8')))
        except (OSError,ValueError): continue
    if not recs: raise SystemExit(L[lang]['b_none'])
    recs.sort(key=lambda r:(r.get('end',''),r.get('start',''),r.get('made','')),reverse=True)
    dst=os.path.join(out,'board.html')
    with open(dst,'w',encoding='utf-8') as f: f.write(board_page(recs,lang))
    return dst

def board_page(recs,lang,site=None,head=''):
    """The board as one HTML document. site (the public site, tools/site) adds the install steps, a language
    switch and its own example receipts; head is extra markup for <head>, such as Open Graph tags."""
    here=os.path.dirname(os.path.abspath(__file__))
    js=lambda v:json.dumps(v,ensure_ascii=False).replace('</','<\\/')
    fill={'__PRINTER__':open(os.path.join(here,'printer.json'),encoding='utf-8').read(),
          '__RECEIPTS__':js(recs),'__SITE__':js(site) if site else 'null',
          '__LANG__':lang,'__TODAY__':datetime.date.today().isoformat()}
    body=re.sub('|'.join(fill),lambda mt:fill[mt.group(0)],open(os.path.join(here,'board_template.html'),encoding='utf-8').read())
    # the first paint is already the right colour: the theme and the page background are set in the head
    return (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            '<meta name="color-scheme" content="dark light">'+head+
            '<script>(function(){var r=document.documentElement,t="dark";try{if(localStorage.getItem("vr-theme")==="light")t="light"}catch(e){}r.setAttribute("data-theme",t);r.classList.add("boot");setTimeout(function(){r.classList.remove("boot")},2500)})();</script>'
            '<style>html{background:#09090b;color-scheme:dark}html[data-theme="light"]{background:#fafafa;color-scheme:light}body{margin:0}[hidden]{display:none!important}</style>'
            '</head><body>'+body+'</body></html>')

def split_minutes(secs,total):
    """Round each item to whole minutes so the items add up to the rounded total (largest remainder)."""
    raw=[s/60 for s in secs]; fl=[int(r) for r in raw]
    for i in sorted(range(len(raw)),key=lambda i:fl[i]-raw[i])[:int(round(total/60))-sum(fl)]: fl[i]+=1
    return fl

def receipt_html(T,lang,name,built,period,span,active_days,d1,items,stats,total,value,thr,bare=False):
    """The share card: a thermal-paper receipt, straight, on a dark card. Returns (html, height).
    bare=True: just the paper on a transparent background (for the video)."""
    e=html.escape
    rows=''.join(f'<span>{q:,}</span><span>{e(l)}</span><span class="r">{t}</span>' for q,l,t in items)
    srows=''.join('<div class="sp"></div>' if r is None else f'<div class="row"><span>{e(r[0])}</span><span>{r[1]}</span></div>' for r in stats)
    H=2*CARD_PAD+804+24*(len(stats)-4)+26*len(items)+24*bool(built)+46*bool(value)+8   # card padding + receipt body + item/BUILT/value rows + slack
    return (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><title>{e(name)} · vibe receipt</title>'
      '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;800&display=swap">'
      f'<style>{RCSS}{RCSS_BARE if bare else ""}</style></head><body><div class="card" style="height:{H}px">'
      '<div class="rc"><div class="tear t"></div><div class="paper">'
      f'<div class="hd"><div class="t">VIBE RECEIPTS</div><div class="mute">github.com/sahmett/vibe-receipts</div><div class="mute ls">{T["rc_kind"]}</div></div>'
      '<div class="hr"></div>'
      f'<div class="row"><span>{T["rc_project"]}</span><span class="nm">{e(name)}</span></div>'
      +(f'<div class="row"><span>{T["rc_built"]}</span><span class="nm">{e(built.upper())}</span></div>' if built else '')+
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
      f'<div class="mute bn">{e(name.upper())} · {d1}</div><div class="ty">THANK YOU FOR VIBING</div></div>'
      '</div><div class="tear b"></div></div></div></body></html>'),H

def find_chrome():
    if os.environ.get('CHROME'): return os.environ['CHROME']
    for p in ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome','/Applications/Chromium.app/Contents/MacOS/Chromium',
              '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge','/Applications/Brave Browser.app/Contents/MacOS/Brave Browser']:
        if os.path.exists(p): return p
    for n in ['google-chrome','google-chrome-stable','chromium','chromium-browser','microsoft-edge','brave-browser']:
        if shutil.which(n): return shutil.which(n)

def render_png(src,dst,w,h,scale=2,transparent=False):
    """Screenshot the card with headless Chrome (2x by default). Returns True if the PNG was written."""
    chrome=find_chrome()
    if not chrome: return False
    if os.path.exists(dst): os.remove(dst)
    try:
        subprocess.run([chrome,'--headless','--disable-gpu','--hide-scrollbars','--no-sandbox',f'--force-device-scale-factor={scale}',
                        f'--window-size={w},{h}','--virtual-time-budget=5000',f'--screenshot={dst}']+
                       (['--default-background-color=00000000'] if transparent else [])+[pathlib.Path(src).as_uri()],
                       capture_output=True,timeout=120)
    except (OSError,subprocess.SubprocessError): return False
    return os.path.exists(dst)

def render_video(paper_png,dst,data,timeout=120):
    """The receipt printing out of a thermal printer: a 1080x1920 clip for Reels, TikTok and Shorts.
    Headless Chrome plays VIDEO_HTML (a canvas animation with a synthesized printer sound) and records it
    in real time with MediaRecorder, so nothing beyond Chrome is needed. The page is served from 127.0.0.1
    so it can post the finished clip back. With ffmpeg installed the clip is re-encoded to constant-frame-rate
    H.264/AAC, which every platform accepts. Returns the path written (.mp4, or .webm if Chrome can only
    record WebM and there is no ffmpeg), or None."""
    chrome=find_chrome()
    if not chrome: return None
    printer=os.path.join(os.path.dirname(os.path.abspath(__file__)),'printer.json')   # built by tools/printer/build.mjs
    if not os.path.exists(printer): return None
    page=VIDEO_HTML.replace('__DATA__',json.dumps(data)).replace('__PRINTER__',open(printer,encoding='utf-8').read()).encode()
    paper=open(paper_png,'rb').read()
    got={}; done=threading.Event()
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*_): pass
        def do_GET(self):
            path=self.path.split('?')[0]
            if path not in ('/','/paper.png'): self.send_error(404); return
            body,ct=(page,'text/html; charset=utf-8') if path=='/' else (paper,'image/png')
            self.send_response(200); self.send_header('Content-Type',ct); self.send_header('Content-Length',str(len(body)))
            self.end_headers(); self.wfile.write(body)
        def do_POST(self):
            body=self.rfile.read(int(self.headers.get('Content-Length') or 0))
            if self.path.startswith('/video'): got['video']=body; got['type']=self.headers.get('Content-Type','')
            else: got['error']=body.decode(errors='ignore')
            self.send_response(204); self.end_headers(); done.set()
    srv=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=srv.serve_forever,daemon=True).start()
    prof=tempfile.mkdtemp(prefix='vibe-receipts-chrome-')
    try:
        proc=subprocess.Popen([chrome,'--headless','--no-sandbox','--hide-scrollbars','--autoplay-policy=no-user-gesture-required',
                               '--window-size=1080,1920','--force-device-scale-factor=1',f'--user-data-dir={prof}','--no-first-run',
                               '--disable-background-timer-throttling','--disable-renderer-backgrounding',
                               f'http://127.0.0.1:{srv.server_address[1]}/?rec=1'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    except OSError:
        srv.shutdown(); shutil.rmtree(prof,ignore_errors=True); return None
    try: done.wait(timeout)
    finally:
        proc.terminate()
        try: proc.wait(10)
        except subprocess.TimeoutExpired: proc.kill()
        srv.shutdown(); shutil.rmtree(prof,ignore_errors=True)
    if 'error' in got: print('Video: the page failed:',got['error'][:300])
    if not got.get('video'): return None
    ext='webm' if 'webm' in got['type'] else 'mp4'
    raw=os.path.splitext(dst)[0]+'.raw.'+ext
    open(raw,'wb').write(got['video'])
    ff=shutil.which('ffmpeg')
    if ff and subprocess.run([ff,'-y','-loglevel','error','-i',raw,'-r','60','-c:v','libx264','-preset','medium','-crf','18',
                              '-pix_fmt','yuv420p','-c:a','aac','-b:a','160k','-movflags','+faststart',dst],capture_output=True).returncode==0:
        os.remove(raw); return dst
    if os.path.exists(dst): os.remove(dst)   # a failed ffmpeg run may leave half a file
    out=os.path.splitext(dst)[0]+'.'+ext
    os.replace(raw,out); return out

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
# the receipt alone on a transparent background, for the video (the paper is cut out and printed line by line)
RCSS_BARE=f"body{{background:transparent}}.card{{width:520px;padding:0;height:auto!important}}.rc{{filter:none}}"

# The video: a thermal printer prints the receipt (paper.png), the receipt is torn off and lands in the middle,
# then the share line. Opened with ?rec=1 it records itself and posts the clip to /video; opened without it,
# it loops as a live preview (click for sound).
VIDEO_HTML=r"""<!doctype html><html><head><meta charset="utf-8"><title>vibe receipt video</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@500;700;800&display=swap">
<style>html,body{margin:0;height:100%;background:#0b0c10;overflow:hidden}canvas{display:block;width:100%;height:100%;object-fit:contain}</style>
</head><body><canvas id="c" width="1080" height="1920"></canvas><script>
const D=__DATA__, W=1080, H=1920, FPS=60, REC=new URLSearchParams(location.search).has('rec');
const FONT='"JetBrains Mono",ui-monospace,Menlo,Consolas,monospace';
const cv=document.getElementById('c'); let g=cv.getContext('2d');
const clamp=(x,a=0,b=1)=>Math.min(b,Math.max(a,x)), lerp=(a,b,t)=>a+(b-a)*t;
const easeOut=t=>1-(1-t)*(1-t), easeIn=t=>t*t, easeInOut=t=>t<.5?4*t*t*t:1-Math.pow(-2*t+2,3)/2;
const fail=m=>fetch('/error',{method:'POST',body:String(m)});
window.onerror=(m,s,l)=>{fail(m+' @'+l)};

const PR=__PRINTER__, GEO=PR.geo;    // the printer from tools/printer/build.mjs: back and front SVG, where the paper leaves the slot
let P, PHw, q, step, n, DP, T, BACK, FRONT, SHADOW;  // paper canvas, its length and px size in world units, line step, steps, step time, print time, timeline, printer layers

function trim(img){                  // cut the transparent margin around the receipt screenshot
  const c=document.createElement('canvas'); c.width=img.width; c.height=img.height;
  const x=c.getContext('2d'); x.drawImage(img,0,0);
  const d=x.getImageData(0,0,c.width,c.height).data; let t=c.height, b=0, l=c.width, r=0;
  for(let y=0;y<c.height;y++) for(let i=0;i<c.width;i++) if(d[(y*c.width+i)*4+3]>8){if(y<t)t=y; if(y>b)b=y; if(i<l)l=i; if(i>r)r=i;}
  const o=document.createElement('canvas'); o.width=r-l+1; o.height=b-t+1;
  o.getContext('2d').drawImage(c,l,t,o.width,o.height,0,0,o.width,o.height); return o;
}

function setup(img){
  P=trim(img); q=GEO.paperW/P.width; PHw=P.height*q;
  step=24*GEO.paperW/520;            // one receipt line (24 css px) per printer step
  n=Math.ceil(PHw/step); DP=clamp(PHw*Math.hypot(...GEO.v)/260,4.5,7);
  const tp0=0.5, tp1=tp0+DP, tt=tp1+0.8, tf0=tt+0.18, tf1=tf0+1.0;
  T={tp0,tp1,tt,tf0,tf1,end:tf1+2.8};
}

const ACC=.12;                       // share of the print spent speeding up, and again slowing down
function printed(t){                 // a steady feed with a soft start and stop: speed is a trapezoid, so no frame jumps
  const x=clamp(t/DP), a=ACC, top=1/(1-a);
  const f=x<a?top*x*x/(2*a):x>1-a?1-top*(1-x)*(1-x)/(2*a):top*(x-a/2);
  return PHw*f;
}
function stepTimes(){                // when the feed passes each line, for the stepper sound
  const out=[];
  for(let i=0;i<n;i++){let lo=0, hi=DP; const want=i*step; for(let k=0;k<30;k++){const m=(lo+hi)/2; if(printed(m)<want) lo=m; else hi=m;} out.push(lo);}
  return out;
}

let BG;                               // the backdrop never changes: painted once, blitted every frame
function bg(){
  if(BG){g.drawImage(BG,0,0); return;}
  BG=document.createElement('canvas'); BG.width=W; BG.height=H; const keep=g; g=BG.getContext('2d');
  g.fillStyle='#0b0c10'; g.fillRect(0,0,W,H);
  let r=g.createRadialGradient(540,820,0,540,820,1050);
  r.addColorStop(0,'rgba(124,92,255,.20)'); r.addColorStop(.55,'rgba(124,92,255,.05)'); r.addColorStop(1,'rgba(0,0,0,0)');
  g.fillStyle=r; g.fillRect(0,0,W,H);
  r=g.createRadialGradient(540,960,700,540,960,1250); r.addColorStop(0,'rgba(0,0,0,0)'); r.addColorStop(1,'rgba(0,0,0,.6)');
  g.fillStyle=r; g.fillRect(0,0,W,H);
  g=keep; g.drawImage(BG,0,0);
}

function layer(img,dy,a){if(a>0){g.save(); g.globalAlpha=a; g.drawImage(img,0,dy,W,H); g.restore();}}

function lamps(dy,a,power,feed){     // the power lamp, and the feed lamp that flickers while it prints
  [power,feed].forEach((on,i)=>{
    if(on<=0||a<=0) return;
    const [x,y]=GEO.leds[i], R=GEO.ledR*10, r=g.createRadialGradient(x,y+dy,0,x,y+dy,R);
    r.addColorStop(0,'rgba(190,255,225,'+(a*on)+')'); r.addColorStop(.12,'rgba(52,211,153,'+(.75*a*on)+')'); r.addColorStop(1,'rgba(52,211,153,0)');
    g.fillStyle=r; g.beginPath(); g.arc(x,y+dy,R,0,7); g.fill();
  });
}

// Affine maps from paper px to screen. On the printer the sheet lies in its leaning plane: s across (GEO.u),
// t up the sheet (GEO.v), the top `o` world units out of the slot. Torn off, it lies flat in the middle.
const mul=(A,B)=>[A[0]*B[0]+A[2]*B[1],A[1]*B[0]+A[3]*B[1],A[0]*B[2]+A[2]*B[3],A[1]*B[2]+A[3]*B[3],A[0]*B[4]+A[2]*B[5]+A[4],A[1]*B[4]+A[3]*B[5]+A[5]];
const turn=(r,cx,cy)=>{const c=Math.cos(r), s=Math.sin(r); return [c,s,-s,c,cx-c*cx+s*cy,cy-s*cx-c*cy];};
function onPrinter(o,sway){
  const u=GEO.u, v=GEO.v, O=GEO.origin, M=[q*u[0],q*u[1],-q*v[0],-q*v[1],O[0]+o*v[0],O[1]+o*v[1]];
  return mul(turn(sway,O[0]+u[0]*GEO.paperW/2,O[1]+u[1]*GEO.paperW/2),M);   // a slight sway about the slot
}
function laidFlat(){
  const s=Math.min(1220/P.height,880/P.width);
  return mul(turn(-.02,540,1020),[s,0,0,s,540-s*P.width/2,1020-s*P.height/2]);
}
function paper(M,clip,shade,shadow){
  g.save(); g.setTransform(...M);
  if(clip!==null){g.beginPath(); g.rect(0,0,P.width,clip/q); g.clip();}
  if(shadow>0){g.save(); g.globalAlpha=shadow; g.drawImage(SHADOW,-SHADOW.pad,-SHADOW.pad+26/M[3]); g.restore();}   // a blurred sprite, not shadowBlur
  g.imageSmoothingQuality='high'; g.drawImage(P,0,0);
  if(shade>0&&clip!==null){            // the paper darkens where it leaves the slot
    const y1=clip/q, y0=y1-7/q, s=g.createLinearGradient(0,y0,0,y1);
    s.addColorStop(0,'rgba(0,0,0,0)'); s.addColorStop(1,'rgba(0,0,0,'+(.38*shade)+')');
    g.fillStyle=s; g.fillRect(0,y0,P.width,y1-y0);
  }
  g.restore();
}

function text(t,y,weight,size,color,a,maxW=980){
  if(a<=0||!t) return;
  g.save(); g.globalAlpha=a; g.textAlign='center'; g.textBaseline='alphabetic'; g.fillStyle=color;
  let s=size; g.font=weight+' '+s+'px '+FONT;
  while(g.measureText(t).width>maxW&&s>18){s-=2; g.font=weight+' '+s+'px '+FONT;}
  g.fillText(t,540,y); g.restore();
}

function draw(t){
  bg();
  const fp=clamp((t-T.tf0)/(T.tf1-T.tf0)), fe=easeInOut(fp);
  const o=t<T.tp0?0:t>=T.tp1?PHw:printed(t-T.tp0);
  const sway=tt=>.004*Math.sin(tt*2.3)*Math.min(1,printed(Math.max(0,Math.min(tt,T.tp1)-T.tp0))/120);
  const dy=600*easeIn(fp), a=1-fp;
  layer(BACK,dy,a);
  lamps(dy,a,t<.35?(Math.sin(t*30)>0?1:.25):1,t>=T.tp0&&t<T.tp1?.7+.3*Math.sin(t*47):0);
  let M;
  if(t<T.tt){                                                            // printing: out of the slot, under the tear bar
    M=onPrinter(o,sway(t)); paper(M,o,1,0); layer(FRONT,0,1);
  } else {                                                               // torn off: a short pull up, then into the middle
    const lift=3.5*easeOut(clamp((t-T.tt)/.15));
    layer(FRONT,dy,a);
    const M0=onPrinter(PHw+lift,sway(T.tt)), M1=laidFlat();
    M=M0.map((x,i)=>lerp(x,M1[i],fe)); paper(M,null,0,fe);
  }
  const cover=clamp((M[5]-280)/220);                                     // the hook fades as the paper rises past it
  text(D.quote,210,'800',58,'#ECEAF2',clamp(.4+t/.25)*Math.max(cover,fe));   // the hook is there from frame one
  const la=clamp((t-T.tf1+.35)/.45);
  text(D.later,320+24*(1-easeOut(la)),'800',80,'#c4b5fd',la);
  const ca=clamp((t-T.tf1)/.5);
  text(D.cta,1736,'500',32,'#8b90a0',ca);
  text(D.url,1796,'700',40,'#ECEAF2',ca);
  text(D.tag,1852,'700',34,'#a78bfa',ca);
}

// --- sound: a stepper whine + paper hiss on every feed step, a rip at the tear. Only recorded, never played
// while recording (headless Chrome would play it out loud).
let ac, dest, out;
function sound(at){                  // schedules the whole soundtrack, `at` = AudioContext time of t=0
  if(!out){out=ac.createGain(); out.gain.value=.9; dest=ac.createMediaStreamDestination(); out.connect(dest); if(!REC) out.connect(ac.destination);}
  const nb=ac.createBuffer(1,ac.sampleRate,ac.sampleRate), ch=nb.getChannelData(0);
  for(let i=0;i<ch.length;i++) ch[i]=Math.random()*2-1;
  const burst=(t0,dur,f,q,vol,type='bandpass',f2)=>{
    const s=ac.createBufferSource(); s.buffer=nb; s.loop=true;
    const fl=ac.createBiquadFilter(); fl.type=type; fl.frequency.setValueAtTime(f,t0); fl.Q.value=q;
    if(f2) fl.frequency.exponentialRampToValueAtTime(f2,t0+dur);
    const e=ac.createGain(); e.gain.setValueAtTime(0,t0); e.gain.linearRampToValueAtTime(vol,t0+.006);
    e.gain.setValueAtTime(vol,t0+dur*.8); e.gain.linearRampToValueAtTime(0,t0+dur);
    s.connect(fl).connect(e).connect(out); s.start(t0); s.stop(t0+dur+.02);
  };
  const whine=(t0,dur)=>{
    const o=ac.createOscillator(); o.type='square'; o.frequency.setValueAtTime(190,t0); o.frequency.linearRampToValueAtTime(240,t0+dur);
    const fl=ac.createBiquadFilter(); fl.type='lowpass'; fl.frequency.value=1100;
    const e=ac.createGain(); e.gain.setValueAtTime(0,t0); e.gain.linearRampToValueAtTime(.05,t0+.008); e.gain.linearRampToValueAtTime(0,t0+dur);
    o.connect(fl).connect(e).connect(out); o.start(t0); o.stop(t0+dur+.02);
  };
  const times=stepTimes(), gap=DP/n;
  for(const t of times){const t0=at+T.tp0+t; burst(t0,gap*.8,3200,.7,.16); whine(t0,gap*.8);}
  burst(at+T.tt,.2,1400,.6,.45,'bandpass',6000);
}

async function main(){
  const svg=x=>{const i=new Image(); i.src=URL.createObjectURL(new Blob([x],{type:'image/svg+xml'})); return i.decode().then(()=>i);};
  const flat=i=>{const c=document.createElement('canvas'); c.width=W; c.height=H; c.getContext('2d').drawImage(i,0,0,W,H); return c;};
  [BACK,FRONT]=(await Promise.all([svg(PR.back),svg(PR.front)])).map(flat);   // rasterised once
  const img=new Image(); img.src='paper.png'; await img.decode(); setup(img);
  const pad=Math.round(30/Math.min(1220/P.height,880/P.width));             // the torn-off sheet's shadow, blurred once
  SHADOW=document.createElement('canvas'); SHADOW.width=P.width+2*pad; SHADOW.height=P.height+2*pad; SHADOW.pad=pad;
  const sx=SHADOW.getContext('2d'); sx.filter='blur('+(pad/2.2)+'px)'; sx.fillStyle='rgba(0,0,0,.6)'; sx.fillRect(pad,pad,P.width,P.height);
  const wait=ms=>new Promise(r=>setTimeout(r,ms));
  await Promise.race([Promise.all(['500','700','800'].map(w=>document.fonts.load(w+' 40px "JetBrains Mono"'))),wait(5000)]);
  draw(0);
  if(!REC){                          // live preview: loops; a click restarts it with sound
    let t0=performance.now();
    addEventListener('click',async()=>{ac=ac||new AudioContext(); await ac.resume(); sound(ac.currentTime+.1); t0=performance.now()+100;});
    const loop=now=>{draw(Math.max(0,(now-t0)/1000)%T.end); requestAnimationFrame(loop);};
    requestAnimationFrame(loop); return;
  }
  ac=new AudioContext(); await ac.resume();
  const a0=ac.currentTime+.1; sound(a0);   // picture and sound run on the audio clock
  const stream=cv.captureStream(FPS); dest.stream.getAudioTracks().forEach(tr=>stream.addTrack(tr));
  const mime=['video/mp4;codecs=avc1.640028,mp4a.40.2','video/mp4;codecs=avc1.42E01F,mp4a.40.2','video/mp4;codecs=avc1,opus',
              'video/mp4','video/webm;codecs=vp9,opus','video/webm'].find(m=>MediaRecorder.isTypeSupported(m));
  const mr=new MediaRecorder(stream,{mimeType:mime,videoBitsPerSecond:14e6,audioBitsPerSecond:160e3}), chunks=[];
  mr.ondataavailable=e=>{if(e.data.size) chunks.push(e.data)};
  mr.onstop=()=>fetch('/video',{method:'POST',headers:{'Content-Type':mime},body:new Blob(chunks,{type:mime})});
  mr.start(500);
  const p0=performance.now()+(a0-ac.currentTime)*1000;   // the frame clock, lined up with the sound once
  const loop=now=>{const t=(now-p0)/1000; draw(clamp(t,0,T.end)); if(t<T.end+.15) requestAnimationFrame(loop); else mr.stop();};
  requestAnimationFrame(loop);
}
main().catch(e=>fail(e&&e.stack||e));
</script></body></html>"""

if __name__=='__main__':
    main()
