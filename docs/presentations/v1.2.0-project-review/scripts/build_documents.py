"""Build the aligned Word speech and Markdown summary from audited local facts."""
from pathlib import Path
import json
import csv
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT=Path(__file__).resolve().parents[1]
facts=json.loads((ROOT/'data/facts.json').read_text(encoding='utf-8'))
content=json.loads((ROOT/'data/slide_content.json').read_text(encoding='utf-8'))
doc=Document()
section=doc.sections[0]
section.page_width=Cm(21);section.page_height=Cm(29.7)
section.top_margin=Cm(1.6);section.bottom_margin=Cm(1.6)
section.left_margin=Cm(1.9);section.right_margin=Cm(1.9)
for name in ['Normal','Title','Subtitle','Heading 1','Heading 2']:
    st=doc.styles[name]
    st.font.name='Microsoft YaHei' if name!='Normal' else 'SimSun'
    st.font.color.rgb=RGBColor(0,0,0)
    st.element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),st.font.name)
normal=doc.styles['Normal'];normal.font.size=Pt(11.5)
normal.paragraph_format.line_spacing=1.2
normal.paragraph_format.space_after=Pt(5)
doc.styles['Heading 1'].font.size=Pt(14)
doc.styles['Heading 1'].paragraph_format.space_before=Pt(12)
doc.styles['Heading 1'].paragraph_format.space_after=Pt(6)
doc.styles['Title'].font.size=Pt(21)
doc.styles['Title'].paragraph_format.space_after=Pt(5)
doc.add_paragraph('WaferSched Agent 项目研究汇报讲稿',style='Title')
p=doc.add_paragraph('v1.2.0　18页PPT对应讲稿　预计20分钟　2026年11月18日')
for run in p.runs:run.font.size=Pt(10)
for i,row in enumerate(content['slides']):
    if i>0 and i%2==0:doc.add_page_break()
    doc.add_heading(f"第{row['page']:02d}页  {row['title']}",level=1)
    p=doc.add_paragraph(f"建议用时 {row['seconds']} 秒。{row['conclusion']}。")
    for run in p.runs:run.bold=True;run.font.size=Pt(10)
    for paragraph in row['speech']:
        doc.add_paragraph(paragraph)
    p=doc.add_paragraph('讲解提示：'+row['cue'])
    for run in p.runs:run.italic=True;run.font.size=Pt(9)
    refs=[]
    for key in row['sources']:
        refs.append(facts['source_index'].get(key,{}).get('path',
                    'data/github_releases.json' if key=='github' else
                    'data/source_index.json' if key=='source_index' else key))
    p=doc.add_paragraph('证据定位：'+'；'.join(refs))
    p.paragraph_format.space_after=Pt(7)
    for run in p.runs:run.font.size=Pt(8);run.font.name='Calibri'
footer=section.footer.paragraphs[0]
footer.alignment=2
field=OxmlElement('w:fldSimple');field.set(qn('w:instr'),'PAGE');footer._p.append(field)
doc.core_properties.title='WaferSched Agent v1.2.0 项目研究汇报逐页讲稿'
doc.core_properties.subject='单臂多腔晶圆设备故障恢复数学优化'
doc.core_properties.author='WaferSched-Agent 项目组'
doc.save(ROOT/'WaferSched-Agent_v1.2.0_逐页汇报讲稿.docx')

project=Path(facts['project_root'])
index=[('项目根目录','.'),('状态与仿真','src/wafer_sched/equipment.py'),('离散事件执行','src/wafer_sched/simulator.py'),
       ('静态CP-SAT','src/wafer_sched/cpsat_model.py'),('PPO','src/wafer_sched/rl/environment.py'),
       ('确定性CFAR','src/wafer_sched/agent/planner.py'),('历史真实LLM','src/wafer_sched/langgraph_agent/graph.py'),
       ('故障恢复','src/wafer_sched/recovery/'),('恢复测试','tests/wafer_sched/test_recovery.py'),
       ('历史LLM数据','results/stage7_langgraph/live-study-002/'),('恢复实验','results/recovery/v1.2.0-acceptance/'),
       ('机器验收','results/recovery/v1.2.0-validation/acceptance.json'),('使用说明','docs/recovery.md'),('项目入口','README.md')]
for _,p in index:assert (project/p).exists()
summary='''# WaferSched-Agent v1.2.0 项目技术摘要

## 数学问题

给定单机械臂多腔设备故障后的在制状态 x 和修复延迟 r，判定是否存在让全部有效晶圆完成剩余工序的调度，记为 F(x,r)。进一步求 ρ*(x)=sup{r≥0:F(x,r)=1}，并在给定可行 r 下最小化剩余 Makespan。立即恢复仍不可行单独报告，不等同于边界为0。

## 方法与已完成范围

原 Simulator 接续历史状态并执行原语取、移、放；恢复 CP-SAT 联合确定候选腔、任务次序和时间；有条件单调边界搜索处理有限、无穷与未知结论；经过全部假设检查的联合资源必要界安全剪枝。离线 LangGraph 复用 SkillRegistry 与 CFAR，根据实际反馈调整查询、预算和目标，并保留已验证方案。

规则调度和 MaskablePPO 是历史静态研究路线。阶段七曾真实调用 DeepSeek；v1.2.0 故障恢复采用离线确定性闭环，未执行真实 LLM 故障恢复决策实验。

## 数学保证

- OPTIMAL 的最优性仅适用于本次优化目标及声明模型；仅查可行性时，不等于最短Makespan。FEASIBLE不包含最优性证明。
- 只有已证INFEASIBLE才收缩不可行上界；UNKNOWN保留已知区间与可行见证。
- 有理输入精确转整数刻度；固定离散次序后的差分约束支持模型内连续时间边界的精确计算。无穷检测使用有数学依据的有限边界上限，不靠任意搜索截止。
- 对称子类：n=m+1，源片共同取完期限D≥2m+1，目标初始为空且全部兼容，p≥D，δ≥1，取放各1秒、移动0秒、无持片上限时，ρ*=D+p+δ−2m−1。异质联合界仅为必要条件。
- 独立仿真和小规模穷举核验实现，不代替一般数学证明；不声称全球首次或已确认开放问题已解决。

## 核验结果

| 实验 | 可追溯结果 |
|---|---|
| 历史F/G静态调度 | 最佳Makespan 63 / 183秒，早期CP为FEASIBLE，后续特定静态编码取得OPTIMAL |
| 阶段七真实LLM | 12轮规划、8轮有效反思；三组44个合法候选 |
| 阶段七活动总时间 | LLM 134.137秒，CFAR 55.419秒，固定流程28.005秒；最终解质量相同 |
| 默认故障恢复 | 最迟修复延迟12秒；边界处最短剩余完工25秒；13秒不可恢复 |
| 恢复对照 | 9类×3方法=27次运行，边界一致；242次查询中116份可行方案重放通过 |
| 独立穷举 | 46次状态与预期一致 |
| 工程验收 | 完整项目265通过1跳过；新环境恢复测试26通过；本轮仅核读已有XML |

性能是固定种子单次合成实验，共享主机验收存在并行任务，不据此宣称普遍加速或LLM优越性。

## 版本与地址

- v1.0.0：原调度方法与CFAR，Git标签存在，当前未查到同名GitHub Release对象。
- v1.1.0：LangGraph与DeepSeek真实LLM研究，Release存在。
- v1.2.0：故障恢复与离线Agent，Release存在；提交7812cc93ea7a860e83b1a534ba669ba4387cbc75，原始发布分支codex/fault-recovery-boundary；本次将该版本及汇报材料整合至main，v1.2.0标签仍保留原始发布提交。
- 仓库：https://github.com/yanq458-tech/WaferSched-Agent
- 版本：https://github.com/yanq458-tech/WaferSched-Agent/releases/tag/v1.2.0

## 文件索引

| 用途 | 实际绝对路径 |
|---|---|
'''
summary+='\n'.join('| '+name+' | `'+str((project/p).resolve())+'` |' for name,p in index)
summary+='''

在项目根目录使用已有环境运行演示：

```powershell
.venv-recovery-acceptance/Scripts/python.exe -m wafer_sched.recovery demo
```

本轮已核验入口代码、环境文件和历史成功记录，未再次运行求解。新环境安装步骤见docs/recovery.md。

## 局限与三个优先方向

当前只支持空故障腔、机械臂动作边界、确定工时及有向三角不等式移动时间；不处理故障腔内晶圆质量、执行中承诺动作或在线求解耗时引起的时钟流逝。

1. **状态接续优先**：支持执行中动作和更复杂WIP。先定义剩余动作与不可取消承诺，再用历史事件重放验证连续性。
2. **精确求解效率其次**：研究更强安全判据、边界搜索、暖启动。沿用同一实例与预算，对照求解规模、证明状态和成本。
3. **真实LLM收益最后**：接入恢复Skill，以相同预算对比确定性Agent，同时统计解质量、证明进度和调用成本。

以上为待实施计划。全部事实和数字的原始文件路径、SHA256与图表绘图数据见data/目录。
'''
(ROOT/'项目技术摘要.md').write_text(summary,encoding='utf-8')

# Export small plot datasets; PPT contains the editable native charts themselves.
chart_rows={
 'stage7_active_time':[{'method':facts['stage7']['arms'][k]['name'],'active_seconds':facts['stage7']['arms'][k]['active_seconds']} for k in ['A','B','C']],
 'recovery_branch_totals':[{'method':m,'branches':sum(int(r['branches']) for r in facts['recovery']['rows'] if r['method']==m)} for m in ['cp_sat_recovery','joint_exact','offline_agent']],
 'historical_baselines':facts['historical_baselines'],
 'default_schedule':facts['demo']['schedule']['transfers']}
for name,rows in chart_rows.items():
    p=ROOT/'charts'/f'{name}.csv'
    with p.open('w',encoding='utf-8-sig',newline='') as h:
        w=csv.DictWriter(h,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
(ROOT/'charts/chart_data.json').write_text(json.dumps(chart_rows,ensure_ascii=False,indent=2),encoding='utf-8')
print('Word speech and technical summary created; slide sections:',len(content['slides']))
