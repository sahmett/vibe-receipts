#!/usr/bin/env python3
"""Builds the README demo from 100% synthetic data.

Creates a throwaway git repo ("pixel-pantry", a made-up recipe app) with back-dated
commits plus fake Claude Code session logs (your prompts + Claude replies), then renders the report with receipts.py.
No real repo or transcript is read.

  python3 demo/make_demo.py            # -> demo/out/pixel-pantry-report.html
  bash to_jpg.sh demo/out/pixel-pantry-report.html
"""
import datetime, json, os, random, shutil, subprocess, sys, tempfile

HERE=os.path.dirname(os.path.abspath(__file__))
ROOT=os.path.dirname(HERE)
OUT=os.path.join(HERE,'out')
random.seed(7)

# (day, [(HH:MM, subject, {path: added_lines})])  — local time
PLAN=[
 ('2026-09-14',[
  ('10:02','chore: scaffold Next.js app + Tailwind',{'package.json':38,'tailwind.config.ts':24,'app/layout.tsx':41}),
  ('10:31','feat: recipe model and seed data',{'lib/recipes.ts':118,'data/seed.json':240}),
  ('11:12','feat: recipe list page with search',{'app/page.tsx':142,'components/SearchBar.tsx':56}),
  ('11:48','feat: recipe detail page',{'app/r/[slug]/page.tsx':164}),
  ('12:20','style: card grid + dark mode',{'components/RecipeCard.tsx':88,'app/globals.css':61}),
  ('15:05','feat: pantry inventory store',{'lib/pantry.ts':131,'components/PantryList.tsx':97}),
  ('15:52','feat: "what can I cook?" matcher',{'lib/match.ts':154,'lib/match.test.ts':92}),
  ('16:40','fix: unit conversion for grams/cups',{'lib/units.ts':73}),
  ('17:15','docs: README + screenshots',{'README.md':80})]),
 ('2026-09-15',[
  ('09:40','feat: auth with magic links',{'app/api/auth/route.ts':121,'lib/session.ts':88}),
  ('10:25','feat: save favourite recipes',{'app/favourites/page.tsx':104,'lib/favourites.ts':66}),
  ('11:10','test: pantry + favourites',{'lib/pantry.test.ts':84,'lib/favourites.test.ts':58}),
  ('11:55','refactor: extract useRecipes hook',{'hooks/useRecipes.ts':72}),
  ('21:30','feat: shopping list from missing ingredients',{'lib/shopping.ts':139,'app/list/page.tsx':118}),
  ('22:18','feat: share list via link',{'app/api/share/route.ts':77}),
  ('23:02','fix: duplicate items when merging lists',{'lib/shopping.ts':24})]),
 ('2026-09-16',[
  ('13:15','feat: meal planner week view',{'app/plan/page.tsx':188,'components/WeekGrid.tsx':126}),
  ('14:02','feat: drag recipes into planner',{'components/WeekGrid.tsx':94,'hooks/useDrag.ts':63}),
  ('14:48','perf: memoize matcher, 3x faster',{'lib/match.ts':38}),
  ('15:30','chore: vendor icon set',{'vendor/icons/sprite.svg':900}),
  ('16:10','feat: nutrition totals per day',{'lib/nutrition.ts':112,'components/DayTotals.tsx':71}),
  ('16:55','fix: timezone bug in planner',{'lib/dates.ts':29})]),
 ('2026-09-17',[
  ('10:20','feat: onboarding flow',{'app/welcome/page.tsx':143}),
  ('11:05','feat: empty states + skeletons',{'components/Empty.tsx':54,'components/Skeleton.tsx':40}),
  ('11:40','chore: CI + lint config',{'.github/workflows/ci.yml':46,'eslint.config.mjs':31}),
  ('12:15','release: v0.1.0 🎉',{'CHANGELOG.md':42,'package.json':2})]),
]

def ts(day,hhmm): return datetime.datetime.fromisoformat(f'{day}T{hhmm}:00').astimezone()

def git(repo,*a,env=None): subprocess.run(['git','-C',repo,*a],check=True,capture_output=True,env=env)

def main():
    tmp=tempfile.mkdtemp(prefix='vibe-receipts-demo-')
    repo=os.path.join(tmp,'pixel-pantry'); logs=os.path.join(tmp,'claude-logs')
    os.makedirs(repo); os.makedirs(logs)
    git(repo,'init','-q','-b','main')
    events=[]
    for day,commits in PLAN:
        prev=None
        for hhmm,subj,files in commits:
            t=ts(day,hhmm)
            for path,n in files.items():
                p=os.path.join(repo,path); os.makedirs(os.path.dirname(p),exist_ok=True)
                with open(p,'a') as f: f.write(''.join(f'// {subj} {i}\n' for i in range(n)))
            git(repo,'add','-A')
            env=dict(os.environ,GIT_AUTHOR_DATE=t.isoformat(),GIT_COMMITTER_DATE=t.isoformat(),
                     GIT_AUTHOR_NAME='Demo Dev',GIT_AUTHOR_EMAIL='demo@example.com',
                     GIT_COMMITTER_NAME='Demo Dev',GIT_COMMITTER_EMAIL='demo@example.com')
            git(repo,'commit','-q','-m',subj,env=env)
            # fake Claude session: your prompts every few minutes (sometimes a longer think),
            # each followed by Claude replies / tool calls that must NOT count as prompts
            start=(prev or t-datetime.timedelta(minutes=random.randint(14,24)))
            if (t-start).total_seconds()>150*60: start=t-datetime.timedelta(minutes=random.randint(14,24))
            cur=start
            while cur<t+datetime.timedelta(minutes=random.randint(2,6)):
                events.append(('user',cur))
                for k in range(random.randint(1,4)):
                    events.append(('assistant',cur+datetime.timedelta(seconds=random.randint(5,90)*(k+1))))
                gap=random.choices([random.uniform(.3,2),random.uniform(2,5),random.uniform(5,12),random.uniform(16,28)],weights=[30,40,24,6])[0]
                cur+=datetime.timedelta(minutes=gap)
            prev=t
    with open(os.path.join(logs,'session.jsonl'),'w') as f:
        for kind,e in events:
            rec={'type':kind,'timestamp':e.astimezone(datetime.timezone.utc).isoformat().replace('+00:00','Z')}
            rec['message']={'role':kind,'content':'demo prompt' if kind=='user' else [{'type':'text','text':'demo reply'}]}
            f.write(json.dumps(rec)+'\n')

    subprocess.run([sys.executable,os.path.join(ROOT,'skills','vibe-receipts','scripts','receipts.py'),repo,
                    '--transcripts',logs,'--lang','en','--out',OUT],check=True)
    shutil.rmtree(tmp)

if __name__=='__main__':
    main()
