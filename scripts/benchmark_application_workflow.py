"""Compare preserved/current helpers on identical local DOM fixtures with no network.

The button changes fixture text only. Tracker preflight and writes are mocked.
No employer applications, live tracker access, resumes or profiles are changed.
"""
import argparse
from contextlib import ExitStack
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import tempfile
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch

from playwright.sync_api import sync_playwright
from application_runtime import BatchSources, Timings
import playwright_batch as current

HTML = '''<h1>Example - Example role</h1><label>Full name<input name="name" required></label>
<label>Email<input name="email" required></label><label>Phone<input name="phone" required></label>
<label>City<input name="city" required></label><label>Resume<input name="resume" type="file" required></label>
<p>example.docx Success!</p><button type="button" id="send"
onclick="document.body.innerHTML='<h1>Application received!</h1>'">Submit application</button>'''


class Locator:
    def __init__(self, obj, timer):self.obj=obj;self.timer=timer
    def __getattr__(self, name):
        value=getattr(self.obj,name)
        if name in ('first','last'):return Locator(value,self.timer)
        if name in ('fill','check','select_option','set_input_files','click','wait_for'):
            def call(*args,**kwargs):
                phase='upload' if name=='set_input_files' else 'confirmation' if name in ('click','wait_for') else 'filling'
                with self.timer.phase(phase):return value(*args,**kwargs)
            return call
        return value


class Frame:
    def __init__(self,obj,timer):self.obj=obj;self.timer=timer
    def __getattr__(self,name):return getattr(self.obj,name)
    def locator(self,*args,**kwargs):return Locator(self.obj.locator(*args,**kwargs),self.timer)
    def wait_for_function(self,*args,**kwargs):
        with self.timer.phase('waiting'):return self.obj.wait_for_function(*args,**kwargs)


class Page(Frame):
    @property
    def frames(self):return [Frame(f,self.timer) for f in self.obj.frames]
    def get_by_text(self,*args,**kwargs):return Locator(self.obj.get_by_text(*args,**kwargs),self.timer)
    def wait_for_timeout(self,*args,**kwargs):
        with self.timer.phase('waiting'):return self.obj.wait_for_timeout(*args,**kwargs)
    def screenshot(self,*args,**kwargs):
        with self.timer.phase('confirmation'):return self.obj.screenshot(*args,**kwargs)


def measure(module,browser,root,n,sources):
    timer=Timings();out=root/str(n);out.mkdir(parents=True)
    resume=out/'example.docx';resume.write_bytes(b'Synthetic fixture - never an employer application')
    page=browser.new_page();network=[]
    page.route('**/*',lambda route:(network.append(route.request.url),route.abort())[-1])
    page.set_content(HTML)
    wrapped=Page(page,timer);state={};inspections=[]
    started=perf_counter()
    with timer.phase('preparation'):
        packet={'id':999000+n,'company':'Example','title':'Example role','resume':str(resume),'row':{'Resume Link':resume.as_uri()}}
        Path('openclaw/application-answers.md').read_text(encoding='utf-8-sig');resume.read_bytes()
    original=module.snapshot
    def snapshot(p):
        inspections.append(1)
        if module is current:
            return original(p)
        with timer.phase('inspection'):return original(p)
    def fresh(_):
        with timer.phase('preparation'):return {'Company':'Example','Job Title':'Example role','Resume Link':resume.as_uri()}
    def tracker(*args,**kwargs):
        with timer.phase('tracker'):return SimpleNamespace(returncode=0,stdout='{"verified":true}',stderr='')
    previous=getattr(module,'SESSION',None)
    # Current helpers use one measured source cache for the whole three-job batch.
    # Keep tracker subprocesses mocked identically in both implementations.
    if module is current:
        module.SOURCES=sources
    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(module,'snapshot',snapshot))
            stack.enter_context(patch.object(module,'fresh_row',fresh))
            stack.enter_context(patch.object(module.subprocess,'run',tracker))
            if module is current:
                stack.enter_context(patch.object(module,'timing',return_value=timer))
            with timer.phase('filling'):module.fill_supported(wrapped,packet,state)
            with timer.phase('confirmation'):
                module.submit(wrapped,packet,state,{'expected_url':'about:blank','selector':'#send',
                    'confirmation_text':'Application received!','all_required_answers_verified':True,'attachment_verified':True},out)
        if network:raise AssertionError('Fixture attempted network access')
        result=timer.report();result['wall_seconds']=perf_counter()-started;result['inspections']=len(inspections)
        return result
    finally:
        module.SESSION=previous
        page.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-source',required=True,type=Path)
    parser.add_argument('--out',required=True,type=Path)
    parser.add_argument('--samples',type=int,default=3)
    args=parser.parse_args()
    spec=importlib.util.spec_from_file_location('application_baseline',args.baseline_source)
    baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)
    results={'kind':'Identical local DOM fixture; native Chrome; all network aborted; tracker mocked',
             'baseline_sha256':hashlib.sha256(args.baseline_source.read_bytes()).hexdigest(),
             'current_sha256':hashlib.sha256(Path(current.__file__).read_bytes()).hexdigest(),
             'current_files':{name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                              for name in ('application_forms.py','application_runtime.py','application_answer_index.json',
                                           'playwright_fast.py','playwright_tracker.py')},
             'before':[],'after':[]}
    sources=BatchSources()
    with tempfile.TemporaryDirectory(prefix='gecko-application-comparison-') as folder,sync_playwright() as pw:
        browser=pw.chromium.launch(channel='chrome',headless=True)
        for n in range(args.samples):
            # Alternate execution order to reduce order/warm-cache bias.
            variants=[('before',baseline),('after',current)]
            if n%2:variants.reverse()
            for name,module in variants:
                results[name].append(measure(module,browser,Path(folder)/name,n,sources))
        browser.close()
    results['source_parse_counts']=sources.parse_counts
    for name in ('before','after'):
        results[name+'_median_seconds']={phase:statistics.median(s['seconds'][phase] for s in results[name])
                                        for phase in results[name][0]['seconds']}
        results[name+'_median_wall_seconds']=statistics.median(s['wall_seconds'] for s in results[name])
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in results.items() if k not in ('before','after')},indent=2))


if __name__=='__main__':main()
