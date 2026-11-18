"""Read existing evidence only. No solver, training, API inference or Git mutation."""
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import os
import urllib.request
import time
import xml.etree.ElementTree as ET

OUT = Path(__file__).resolve().parents[1]
ROOT = OUT.parents[2]
DATA = OUT / 'data'
DATA.mkdir(exist_ok=True)
sources = {}

def source(key, relative):
    p = ROOT / relative
    assert p.exists(), str(p)
    sources[key] = {'path': relative, 'absolute_path': str(p),
                    'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
    return p

def js(key, relative):
    return json.loads(source(key, relative).read_text(encoding='utf-8-sig'))

def table(key, relative):
    p = source(key, relative)
    rows = list(csv.DictReader(p.open(encoding='utf-8-sig', newline='')))
    (DATA / (key + '.csv')).write_bytes(p.read_bytes())
    return rows

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True, encoding='utf-8').strip()

def write(name, value):
    (DATA / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

facts = {'as_of_local_date': '2026-11-18', 'project_root': str(ROOT),
         'branch': git('branch','--show-current'), 'head': git('rev-parse','HEAD'),
         'baseline_worktree': git('status','--short')}
facts['tags'] = {tag: git('rev-parse',tag+'^{}') for tag in ('v1.0.0','v1.1.0','v1.2.0')}
facts['version_contents'] = {}
for tag in facts['tags']:
    files = git('ls-tree','-r','--name-only',tag).splitlines()
    facts['version_contents'][tag] = {name: any(p.startswith(prefix) for p in files)
        for name,prefix in [('CFAR','src/wafer_sched/agent/'),('LangGraph','src/wafer_sched/langgraph_agent/'),
                            ('recovery','src/wafer_sched/recovery/')]}
facts['remote_refs'] = git('ls-remote','origin','refs/heads/main','refs/tags/v1.0.0^{}',
                          'refs/tags/v1.1.0^{}','refs/tags/v1.2.0^{}')
releases = []
credential = subprocess.run(['git','credential','fill'], input='protocol=https\nhost=github.com\n\n',
    text=True,capture_output=True,cwd=ROOT,timeout=30,
    env=dict(os.environ,GIT_TERMINAL_PROMPT='0',GCM_INTERACTIVE='Never'))
secret = dict(line.split('=',1) for line in credential.stdout.splitlines() if '=' in line).get('password')
for tag in facts['tags']:
    url = 'https://api.github.com/repos/yanq458-tech/WaferSched-Agent/releases/tags/' + tag
    last = None
    for retry in range(3):
        try:
            # Credential travels via stdin, never command arguments, output or saved data.
            config = 'header = "User-Agent: WaferSched-report-readonly"\n'
            if secret:
                config += 'header = "Authorization: Bearer '+secret+'"\n'
            response = subprocess.run(['curl.exe','--silent','--show-error','--max-time','20','--write-out','\n%{http_code}',
                '--config','-',url],input=config,capture_output=True,text=True,encoding='utf-8',timeout=25)
            if response.returncode:
                raise RuntimeError('GitHub read failed')
            payload, http_status = response.stdout.rsplit('\n',1)
            if http_status=='404':
                releases.append({'tag_name':tag,'draft':None,'status':'no_GitHub_Release_found',
                                 'note':'Git tag exists; no release object at this API endpoint'})
                break
            if http_status!='200':
                raise RuntimeError('GitHub status '+http_status)
            r = json.loads(payload)
            releases.append({k:r[k] for k in ('tag_name','name','draft','prerelease','published_at','html_url','body')})
            break
        except Exception as e:
            last = e
            time.sleep(.5)
    else:
        raise RuntimeError(f'Release verification failed: {tag}: {type(last).__name__}')
facts['releases'] = releases
write('github_releases.json', releases)
comparison = table('stage7_comparison', 'results/stage7_langgraph/live-study-002/comparison.csv')
decisions = table('stage7_decisions', 'results/stage7_langgraph/live-study-002/B/decisions.csv')
facts['historical_baselines'] = [
    {'round':r['round'],'scenario':r['scenario_id'],'method':r['method'],'parameters':json.loads(r['parameters']),
     'makespan':float(r['makespan_seconds']),'solver_status':r['solver_status']}
    for r in decisions]
audit = js('stage7_llm_audit', 'results/stage7_langgraph/live-study-002/llm_execution_audit.json')
saved = js('stage7_saved_evidence', 'results/stage7_langgraph/v1.1.0-audit/saved_evidence.json')
arms = {}
for key, name in [('A','确定性 CFAR'),('B','真实 LLM'),('C','固定流程')]:
    rows = [r for r in comparison if r['arm'] == key]
    assert len({r['total_active_research_wall_seconds'] for r in rows}) == 1
    arms[key] = {'name':name, 'rounds':sum(int(r['rounds']) for r in rows),
                 'active_seconds':float(rows[0]['total_active_research_wall_seconds']),
                 'tool_seconds':float(rows[0]['total_tools_seconds']),
                 'best':{r['scenario_id']:float(r['best_makespan_seconds']) for r in rows}}
facts['stage7'] = {'arms':arms, 'llm_planned_rounds':int(comparison[2]['real_llm_planned_rounds']),
                  'valid_reflections':audit['complete_valid_llm_reflections'],
                  'verified_candidates':saved['saved_candidates_verified'],
                  'actual_api_requests':audit['actual_api_requests'],
                  'termination':audit['termination']}
assert facts['stage7']['llm_planned_rounds']==12 and facts['stage7']['valid_reflections']==8
stage6 = js('stage6_analysis','results/wafer_sched/stage6/analysis.json')
facts['stage6'] = {k:stage6[k] for k in ('experiment_count','verified_count','ablation')}
results = table('recovery_results','results/recovery/v1.2.0-acceptance/results.csv')
accept = js('acceptance','results/recovery/v1.2.0-validation/acceptance.json')
summary = js('recovery_summary','results/recovery/v1.2.0-acceptance/summary.json')
oracle = js('enumeration','results/recovery/v1.2.0-acceptance/independent_enumeration.json')
assert len(results)==27 and len(oracle)==46 and all(r['status']==r['expected'] for r in oracle)
queries = []
for row in results:
    path = ROOT/'results/recovery/v1.2.0-acceptance'/row['scenario']/row['method']
    for p in sorted(path.glob('query-*/result.json')):
        r = json.loads(p.read_text(encoding='utf-8'))
        queries.append(r)
assert len(queries)==242
feasible = [r for r in queries if r['status'] in ('FEASIBLE','OPTIMAL')]
assert len(feasible)==116 and all(r['verification']['valid'] for r in feasible)
facts['recovery'] = {'summary':summary,'rows':results,'raw_query_count':len(queries),
                     'raw_verified_count':len(feasible),'enumeration_queries':len(oracle)}
for key, filename in [('full','full-suite.xml'),('clean','clean-environment-tests.xml')]:
    xml = ET.parse(source('tests_'+key,'results/recovery/v1.2.0-validation/'+filename))
    suites = xml.getroot().findall('testsuite')
    totals = {k:sum(int(s.get(k,0)) for s in suites) for k in ('tests','failures','errors','skipped')}
    totals['passed'] = totals['tests']-totals['failures']-totals['errors']-totals['skipped']
    facts['tests_'+key] = totals
assert facts['tests_full']['passed']==265 and facts['tests_clean']['passed']==26
demo = js('demo_solution','results/recovery/v1.2.0-demo/demo_schedule/query-000/result.json')
facts['demo'] = {'status':demo['status'],'repair_delay':demo['repair_delay_seconds'],
                 'makespan':demo['makespan_seconds'],'makespan_optimal':demo['makespan_optimal'],
                 'schedule':demo['schedule']}
assert facts['demo']['repair_delay']==12 and facts['demo']['makespan']==25 and facts['demo']['makespan_optimal']
late = [r for r in queries if r.get('repair_delay_seconds')==13 and r['status']=='INFEASIBLE']
assert late
facts['demo']['late_delay_13_infeasible_saved_queries']=len(late)
for key, path in [('agent_finite','symmetric_3/offline_agent/boundary.json'),
                  ('agent_heterogeneous','heterogeneous_p/offline_agent/boundary.json'),
                  ('agent_unbounded','unbounded_bypass/offline_agent/boundary.json'),
                  ('agent_unknown','unknown_retry/agent.json'),('agent_budget','budget_exhausted/agent.json')]:
    value = js(key,'results/recovery/v1.2.0-acceptance/'+path)
    facts[key] = {'status':value['status'],'stop_reason':value['stop_reason'],
                  'history':[{'phase':h['proposal']['phase'],'r_tick':h['proposal']['query_tick'],
                    'budget':h['proposal']['max_seconds'],'status':h['result']['status']} for h in value['history']]}
code = ['simulator.py','equipment.py','actions.py','verification.py','cpsat_model.py','cpsat_solver.py',
        'policies/rules.py','rl/environment.py','rl/training.py','agent/planner.py','agent/feedback.py',
        'agent/skills.py','langgraph_agent/graph.py','langgraph_agent/llm.py',
        'recovery/state.py','recovery/model.py','recovery/solver.py','recovery/boundary.py',
        'recovery/bounds.py','recovery/replay.py','recovery/enumeration.py','recovery/agent.py',
        'recovery/experiments.py','recovery/__main__.py']
for p in code:
    source(p, 'src/wafer_sched/'+p)
for key,p in [('recovery_docs','docs/recovery.md'),('stage7_docs','docs/wafer_sched_stage7.md'),
              ('recovery_tests','tests/wafer_sched/test_recovery.py'),('README','README.md'),
              ('deps','requirements-recovery.txt')]: source(key,p)
facts['source_index'] = sources
write('facts.json', facts)
write('source_index.json',sources)
lines=['# 项目事实清单','',f"核对日期：{facts['as_of_local_date']}。本轮只读现有证据，未重新运行求解或训练。",'',
       f"当前分支：`{facts['branch']}`；提交：`{facts['head']}`。",'',
       '| 事实 | 核验结果 | 原始来源 |','|---|---|---|']
rows=[('版本关系','v1.0.0 CFAR；v1.1.0 增加真实LLM；v1.2.0 增加恢复模块','Git标签树及 data/github_releases.json'),
      ('阶段七','12轮真实LLM规划、8轮有效反思、44个合法候选','stage7_comparison.csv；llm_execution_audit.json；saved_evidence.json'),
      ('阶段七活动总时间','CFAR 55.419秒，LLM 134.137秒，固定流程28.005秒','live-study-002/comparison.csv，每个arm去重后取总时间'),
      ('F/G最佳','63/183秒，静态实验；不作为故障恢复指标','stage6/analysis.json；stage7 comparison.csv'),
      ('默认恢复例','修复延迟12秒，最短剩余完工25秒；13秒不可恢复','v1.2.0-demo/demo_schedule/query-000/result.json；保存的不可行查询'),
      ('对照运行','9类×3方法=27次，242次查询，116份合法方案','逐个读取各 scenario/method/query-*/result.json'),
      ('独立枚举','46次，status逐条等于expected','independent_enumeration.json'),
      ('测试','265通过1跳过；独立环境26通过','两份JUnit XML，不只引用验收摘要'),
      ('保证范围','确定性有理时间模型；空故障腔；动作边界；条件剪枝','recovery/state.py、model.py、bounds.py；docs/recovery.md'),
      ('研究保证','定义、条件证明、数值核验分别标记；不声称全球首次','docs/recovery.md及本轮讲稿')]
lines += ['| '+' | '.join(r)+' |' for r in rows]
lines += ['', '源文件的实际绝对路径和SHA256见 `data/source_index.json`。',
          '阶段七原始提案中的“最优”措辞不直接作为证据；汇报区分早期FEASIBLE与后续特定静态编码的OPTIMAL。',
          'v1.2.0性能来自共享主机单次合成实验，验收期间有并行任务，不作为受控加速比结论。']
(OUT/'项目事实清单.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({'sources':len(sources),'branch':facts['branch'],'head':facts['head'],
                  'releases':[(r['tag_name'],r['draft']) for r in releases],
                  'queries':len(queries),'verified':len(feasible)},ensure_ascii=False))
