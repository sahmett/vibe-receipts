"""Tests for receipts.py (standard library only):  python3 -m unittest discover -s tests -v"""
import contextlib, csv, io, json, os, re, subprocess, sys, tempfile, unittest

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,os.path.join(ROOT,'skills','vibe-receipts','scripts'))
import receipts as R

def rec(ts,content,type='user',**kw):
    return dict(type=type,timestamp=f'2026-06-01T{ts}Z',message=dict(role=type,content=content),**kw)

def write_log(folder,records,name='s.jsonl'):
    with open(os.path.join(folder,name),'w',encoding='utf-8') as f:
        for r in records: f.write(json.dumps(r)+'\n')

class Small(unittest.TestCase):
    def test_pctl(self):
        self.assertEqual(R.pctl([],50),0)
        self.assertEqual(R.pctl([1,2,3,4],50),2.5)
        self.assertEqual(R.pctl([1,2,3,4,5],25),2)

    def test_split_minutes_adds_up(self):
        secs=[100,100,100]                       # 1.67 min each, 5 min in all
        self.assertEqual(sum(R.split_minutes(secs,sum(secs))),5)
        self.assertEqual(R.split_minutes([0,90,0],90),[0,2,0])   # round(1.5) = 2, and it goes to the row that has the time
        self.assertEqual(R.split_minutes([],0),[])

    def test_kind(self):
        for path,k in {'src/ui/button.js':'code','ui/app.css':'code','lib/a.py':'code','package.json':'config',
                       'vendor/x.js':'vendor','node_modules/a/b.js':'vendor','uv.lock':'gen','Cargo.lock':'gen','go.sum':'gen',
                       'dist/app.js':'gen','public/logo.svg':'gen','nb/a.ipynb':'gen','__snapshots__/a.snap':'gen',
                       'README.md':'doc','docs/guide.html':'doc'}.items():
            self.assertEqual(R.kind(path),k,path)

    def test_token_value(self):
        per={'a':dict(input_tokens=1_000_000,cache_creation_input_tokens=1_000_000,cache_read_input_tokens=1_000_000,output_tokens=1_000_000),
             'b':dict(input_tokens=5,cache_creation_input_tokens=0,cache_read_input_tokens=0,output_tokens=5)}
        inp,out,rd=R.PRICES['claude-opus-5-5']
        v=R.token_value(per,{'a':'claude-opus-5-5-20260101[1m]','b':'claude-unknown-9'},{'a':400_000},set())
        self.assertAlmostEqual(v['input'],inp); self.assertAlmostEqual(v['output'],out); self.assertAlmostEqual(v['cache_read'],rd)
        self.assertAlmostEqual(v['cache_write'],0.6*inp*1.25+0.4*inp*2)        # 5-minute and 1-hour cache writes
        self.assertEqual(v['unpriced'],1)
        fast=R.token_value(per,{'a':'claude-opus-5-5'},{},{'a'})
        self.assertAlmostEqual(fast['output'],2*out)

    def test_long_prompt_price(self):
        use=lambda read: {'a':dict(input_tokens=0,cache_creation_input_tokens=0,cache_read_input_tokens=read,output_tokens=1_000_000)}
        short=R.token_value(use(100_000),{'a':'claude-haiku-5-5'},{},set())
        long=R.token_value(use(100_001),{'a':'claude-haiku-5-5'},{},set())
        self.assertAlmostEqual(short['output'],0.50); self.assertAlmostEqual(long['output'],2.50)
        self.assertAlmostEqual(long['cache_read'],100_001*0.05/1e6)

    def test_current_models_are_priced(self):
        for m in ('claude-fable-5-2','claude-mythos-5-2','claude-opus-5-5','claude-sonnet-5-5','claude-haiku-5-5'):
            self.assertIn(m,R.PRICES)

class Prompts(unittest.TestCase):
    def load(self,records):
        with tempfile.TemporaryDirectory() as d:
            write_log(d,records)
            return R.load_prompts([d],'0000-00-00','9999-99-99')

    def test_what_counts(self):
        ask=rec('10:01:00',[dict(type='tool_use',id='ask1',name='AskUserQuestion',input={})],type='assistant')
        got=self.load([
            rec('10:00:00','add auth'),                                                          # typed
            ask,
            rec('10:02:00',[dict(type='tool_result',tool_use_id='ask1',content='magic links')]), # your answer to a question
            rec('10:03:00',[dict(type='tool_result',tool_use_id='other',content='ok')]),         # tool output
            rec('10:04:00',[dict(type='text',text='<system-reminder>context</system-reminder>'),
                            dict(type='text',text='now the tests')]),                            # typed, behind a reminder block
            rec('10:05:00',[dict(type='text',text='<system-reminder>only this</system-reminder>')]),
            rec('10:06:00','<command-name>/clear</command-name>'),
            rec('10:07:00','[Request interrupted by user]'),
            rec('10:08:00','why was the Request interrupted earlier?'),                          # typed: mentions the marker
            rec('10:09:00','meta',isMeta=True),
            rec('10:10:00','side',isSidechain=True),
            rec('10:11:00','summary',isCompactSummary=True),
            rec('10:12:00','   '),
        ])
        self.assertEqual(len(got),4)

class Cli(unittest.TestCase):
    def run_cli(self,*args):
        return subprocess.run([sys.executable,os.path.join(ROOT,'skills','vibe-receipts','scripts','receipts.py'),*args],capture_output=True,text=True)

    def test_bad_arguments_are_refused(self):
        for args in (['--since','2026-6-1x'],['--until','june'],['--break','abc'],['--break','0'],['--break','-5']):
            r=self.run_cli('.',*args)
            self.assertEqual(r.returncode,2,args); self.assertNotIn('Traceback',r.stderr)

    def test_name_with_a_slash_becomes_a_file_name(self):
        with tempfile.TemporaryDirectory() as logs, tempfile.TemporaryDirectory() as out:
            write_log(logs,[rec('10:00:00','a'),rec('10:05:00','b')])
            r=self.run_cli(out,'--transcripts',logs,'--out',out,'--no-png','--lang','en','--name','client/app')
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertTrue(os.path.exists(os.path.join(out,'client-app-daily.csv')))

class Demo(unittest.TestCase):
    """The synthetic demo is the end-to-end test: the README shows these numbers."""
    def test_demo_numbers(self):
        with tempfile.TemporaryDirectory() as out:
            r=subprocess.run([sys.executable,os.path.join(ROOT,'demo','make_demo.py'),'--no-png','--out',out],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertRegex(r.stdout,r'Working time\s*: 11h 05m\s+\(205 prompts')
            self.assertIn('Commits        : 26   (Effective code 3293 lines)',r.stdout)
            self.assertNotIn('unpriced',r.stdout)
            with open(os.path.join(out,'pixel-pantry-daily.csv'),encoding='utf-8') as f: rows=list(csv.DictReader(f))
            self.assertEqual(sum(int(x['work_min']) for x in rows),11*60+5)        # the days add up to the headline
            self.assertEqual(sum(int(x['prompts']) for x in rows),205)

if __name__=='__main__':
    unittest.main()
