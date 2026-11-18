import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {createRequire} from 'node:module';

const ROOT=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const runtime=process.env.CODEX_RUNTIME || path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime');
const modules=path.join(runtime,'dependencies/node/node_modules');
process.env.RUNTIME_NODE_MODULES=modules;
const require=createRequire(path.join(modules,'__runtime__.cjs'));
const {Presentation,PresentationFile}=await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
const SKILL=process.env.PRESENTATIONS_SKILL || path.join(os.homedir(),'.codex/plugins/cache/openai-primary-runtime/presentations/26.1116.12010/skills/presentations');
const {finalizePresentation,applyPresentationChartFont}=await import(pathToFileURL(path.join(SKILL,'container_tools/artifact_tool_utils.mjs')).href);
const facts=JSON.parse(await fs.readFile(path.join(ROOT,'data/facts.json'),'utf8'));
const content=JSON.parse(await fs.readFile(path.join(ROOT,'data/slide_content.json'),'utf8'));
const C={navy:'#17324D',ink:'#162B3F',teal:'#007F78',blue:'#3979AF',red:'#C45142',muted:'#586B7D',light:'#E9F1F5',line:'#CED9E2',paper:'#FAFCFD',white:'#FFFFFF',amber:'#B97428'};
const FONT='Microsoft YaHei',MATH='Cambria Math';
const pres=Presentation.create({slideSize:{width:1280,height:720}});
const boxes=[];
function shape(s,x,y,w,h,fill=C.white,line='none',geometry='rect'){
 return s.shapes.add({geometry,position:{left:x,top:y,width:w,height:h},fill,line:{fill:line,width:line==='none'?0:1.5,style:'solid'}});
}
function text(s,txt,x,y,w,h,size=25,color=C.ink,bold=false,align='left',font=FONT){
 const o=shape(s,x,y,w,h,'none');o.text=txt;
 o.text.style={fontSize:size,typeface:font,color,bold,alignment:align,verticalAlignment:'middle',insets:0,autoFit:'none',wrap:'square'};
 boxes.push({slide:pres.slides.items.length,text:txt,x,y,w,h,size,font});return o;
}
function line(s,x,y,w,color=C.line){shape(s,x,y,w,1.3,color);}
function arrow(s,x,y,w,h=18,color=C.teal,down=false){shape(s,x,y,w,h,color,'none',down?'downArrow':'rightArrow');}
function eq(s,txt,x,y,w,h=50,size=34,color=C.navy){return text(s,txt,x,y,w,h,size,color,false,'left',MATH);}
function metric(s,value,label,x,y,w=240,color=C.teal){text(s,value,x,y,w,70,52,color,true);text(s,label,x,y+72,w,50,22,C.muted);}
function table(s,rows,x,y,width,height,colWidths,size=22){
 const t=s.tables.add({rows:rows.length,columns:rows[0].length,left:x,top:y,width,height,columnWidths:colWidths,values:rows});
 t.borders.assign({fill:C.line,width:1,style:'solid'});
 for(let r=0;r<rows.length;r++)for(let c=0;c<rows[r].length;c++){
  const cell=t.getCell(r,c);cell.fill=r===0?C.navy:(r%2?C.white:C.paper);
  cell.text.style={fontSize:size,typeface:FONT,color:r===0?C.white:C.ink,bold:r===0,verticalAlignment:'middle',alignment:'left',insets:8,autoFit:'none'};
 }
 return t;
}
function chart(s,{x,y,w,h,title,categories,series,max,unit='秒',format='0',legend=true}){
 const c=s.charts.add('bar',{position:{left:x,top:y,width:w,height:h},title,titleTextStyle:{typeface:FONT,fontSize:24,bold:true,fill:C.navy},
 categories,series,hasLegend:legend,legend:{position:'bottom',textStyle:{typeface:FONT,fontSize:18}},
 barOptions:{direction:'column',grouping:'clustered',gapWidth:80},chartFill:C.white,plotAreaFill:C.white,
 xAxis:{textStyle:{typeface:FONT,fontSize:19},line:{fill:C.line,width:1}},
 yAxis:{min:0,...(max?{max}:{}),title:{text:unit,textStyle:{typeface:FONT,fontSize:18}},numberFormatCode:format,
        textStyle:{typeface:FONT,fontSize:17},majorGridlines:{fill:C.line,width:1}},
 dataLabels:{showValue:true,position:'outEnd',numberFormatCode:format,textStyle:{typeface:FONT,fontSize:18}}});
 applyPresentationChartFont(c,{fontFamily:FONT});return c;
}
const sourceFoot={
 2:'recovery/examples.py；v1.2.0-demo/input.json',3:'解释性构造；计时语义见 actions.py、recovery/model.py',
 4:'recovery/boundary.py、solver.py；docs/recovery.md',5:'recovery/state.py、model.py、replay.py',
 6:'recovery/model.py、solver.py；docs/recovery.md',7:'recovery/boundary.py；docs/recovery.md 的差分约束论证',
 8:'recovery/bounds.py；docs/recovery.md；test_recovery.py',9:'policies/rules.py；rl/environment.py；agent/skills.py',
 10:'langgraph_agent/graph.py；recovery/agent.py；agent/feedback.py',11:'v1.2.0-acceptance 各场景的 offline_agent/boundary.json 及 unknown_retry/agent.json',
 12:'本地 Git 标签目录树与 GitHub Release API，核对于 2026-11-18',13:'stage7_langgraph/live-study-002/B/decisions.csv；阶段六 analysis.json',
 14:'live-study-002/comparison.csv、llm_execution_audit.json、v1.1.0-audit/saved_evidence.json',
 15:'v1.2.0-demo/demo_schedule/query-000/result.json；保存的 r=13 不可行查询',
 16:'v1.2.0-acceptance/results.csv、summary.json、independent_enumeration.json；两份JUnit XML',
 17:'实际文件扫描及 data/source_index.json；GitHub v1.2.0 Release',18:'docs/recovery.md；v1.2.0-validation/acceptance.json；后续计划尚未实施'};
function base(i){
 const s=pres.slides.add();s.background.fill=C.white;
 const c=content.slides[i-1];
 text(s,c.title,54,42,1172,66,c.title.length>26?39:43,C.navy,true);
 text(s,c.conclusion,56,118,1165,52,25,C.muted);
 line(s,56,657,1168);
 text(s,'来源：'+(sourceFoot[i]||'项目已发布代码与验收记录'),56,666,1110,35,14,C.muted);
 text(s,String(i).padStart(2,'0'),1180,666,46,35,16,C.muted,false,'right');
 s.speakerNotes.text=c.speech.join('\n\n')+'\n\n讲解提示：'+c.cue+'\n\n证据：\n'+c.sources.map(k=>facts.source_index[k]?.absolute_path||k).join('\n');
 return s;
}

// 01 — editable typography, no decorative evidence.
{
 const s=pres.slides.add();s.background.fill=C.navy;
 text(s,'WaferSched-Agent   v1.2.0',64,76,1100,50,27,'#90CBC7',true);
 text(s,'单臂多腔晶圆设备\n故障恢复数学优化',64,184,1120,172,64,C.white,true);
 text(s,'可恢复性判定、最迟修复时限\n与自主精确重调度',68,390,1080,105,34,'#DDEBF4');
 text(s,'计算数学与智能体交叉研究\n项目研究汇报  2026年11月18日',68,575,1000,80,24,'#DDEBF4');
 s.speakerNotes.text=content.slides[0].speech.join('\n\n');
}
// 02 — requested native equipment schematic.
{
 const s=base(2);
 const box=(label,x,y,w,h,fill=C.light,stroke=C.line)=>{shape(s,x,y,w,h,fill,stroke);text(s,label,x+10,y+10,w-20,h-20,25,C.navy,true,'center');};
 box('源腔 S1\n晶圆 W1',66,220,195,95);box('源腔 S2\n晶圆 W2',66,345,195,95);box('源腔 S3\n晶圆 W3',66,470,195,95);
 box('单机械臂\n单夹爪',380,333,208,110,'#E1F0EE',C.teal);
 box('健康腔 H1',728,220,210,80);box('健康腔 H2',728,345,210,80);box('故障腔 F\n修复后可放片',728,470,210,100,'#F8E8E5',C.red);
 arrow(s,275,367,90);arrow(s,604,367,105);box('OUT\n全部工序完成',1030,333,190,110,C.light);
 arrow(s,950,367,65);line(s,720,260,1);
 text(s,'S1/S2/S3  →  H1/H2/F  →  OUT',290,200,410,52,24,C.teal,true);
 text(s,'必须在 6 s 内取完源片',300,485,380,45,25,C.red,true);
 text(s,'目标加工 10 s\n加工后驻留上限 1 s',975,482,260,86,23,C.muted);
 text(s,'默认例：取 1 s，放 1 s，移动 0 s；箭头表示允许的路线，不是执行次序。',65,599,1130,39,23,C.muted);
}
// 03 — explanatory construction, never represented as a new experiment.
{
 const s=base(3);text(s,'两片均已加工完成，只需卸到 OUT；各自最迟取完时刻为 1 s',64,184,1160,47,25,C.navy,true);
 const x0=300,k=230;
 for(const [label,y] of [['只看 W1',290],['只看 W2',380],['一起调度',505]])text(s,label,66,y,210,50,28,C.navy,true);
 for(const y of [290,380]){shape(s,x0,y,k,50,C.teal);text(s,'取片 0–1',x0,y,k,50,25,C.white,true,'center');shape(s,x0+k,y,k,50,C.blue);text(s,'放 OUT 1–2',x0+k,y,k,50,25,C.white,false,'center');}
 shape(s,x0,505,k,50,C.teal);text(s,'取 W1',x0,505,k,50,25,C.white,true,'center');
 shape(s,x0+k,505,k,50,C.blue);text(s,'放 W1',x0+k,505,k,50,25,C.white,false,'center');
 shape(s,x0+2*k,505,k,50,C.red);text(s,'取 W2 2–3',x0+2*k,505,k,50,25,C.white,true,'center');
 for(let i=0;i<=3;i++)text(s,String(i)+' s',x0+i*k-25,570,65,35,23,C.muted,false,'center');
 text(s,'各自都来得及',855,325,330,55,32,C.teal,true);
 text(s,'第二片超期，交换顺序也无解',65,608,1100,38,26,C.red,true);
}
// 04 — formal objects, with empty-set and infinity semantics.
{
 const s=base(4);
 const ys=[202,337,478];
 for(let i=0;i<3;i++)text(s,['1  存在性','2  修复容忍度','3  调度质量'][i],65,ys[i],270,50,29,C.teal,true);
 eq(s,'F(x,r) = 1 ⇔ 存在合法完成调度',365,195,810,55,35);
 text(s,'x：故障时完整状态    r：修复延迟（从快照起计时）',365,254,820,46,25,C.muted);
 eq(s,'ρ*(x) = sup { r ≥ 0 : F(x,r) = 1 }',365,330,820,60,40);
 text(s,'有限：边界可达到    无穷：无有限上界\n立即恢复仍不可行：单独返回状态，不能写成 ρ*=0',365,394,840,75,23,C.muted);
 eq(s,'min Cmax     s.t. 全部工艺、资源和期限约束',365,481,840,60,32);
 text(s,'在给定可行 r 下，最小化最后一片离开设备的时刻',365,548,840,60,25,C.muted);
}
// 05 — editable variable/constraint timeline.
{
 const s=base(5);
 const x=80,y=218;
 const chunks=[['取片',170,C.blue],['移动 / 持片等待',280,C.light],['放片',170,C.teal],['加工',280,'#CBE4E1']];
 let px=x;for(const [label,w,color] of chunks){shape(s,px,y,w,60,color);text(s,label,px+5,y+8,w-10,44,25,color===C.blue||color===C.teal?C.white:C.navy,true,'center');px+=w;}
 for(const [label,xx] of [['a',80],['b',250],['u',530],['v',700],['c',980]])eq(s,label,xx-5,282,70,45,33);
 text(s,'z：选择兼容腔',1040,225,190,55,24,C.navy,true);
 eq(s,'b = a + τpick      v = u + τplace      u ≥ b + tmove',65,345,1150,50,32);
 table(s,[['约束','模型中的含义'],['工艺与驻留','下一次 a ≥ c；下一次 b ≤ c + δ'],['腔室容量','从放片开始 u 到下次取片完成 b 独占'],['单臂互斥','持片区间 [a,v) 不重叠，另计空臂移动'],['故障与历史','故障腔 u ≥ r；既有加工和驻留计时继续累计']],65,414,1150,215,[220,930],23);
}
// 06 — native solver status table.
{
 const s=base(6);
 text(s,'整数时间 + 布尔选择 + 区间 NoOverlap + 机械臂顺序 Circuit',65,190,1150,55,28,C.teal,true);
 table(s,[['返回状态','可以说什么','不能越过的保证范围'],['OPTIMAL','优化调用：已证模型内最优','仅查可行性时，不代表最短 Makespan'],['FEASIBLE','找到合法候选方案','最优性尚未证明'],['INFEASIBLE','支持范围内的完整模型已证无解','不能扩大到未建模的物理动作'],['UNKNOWN','当前预算内未取得确定结论','不能缩小不可行上界']],65,270,1150,282,[220,430,500],23);
 text(s,'精确时间刻度：有理输入转整数，不四舍五入；最高 10000 ticks/s。',65,576,1150,42,24,C.muted);
}
// 07 — search flow; all nodes editable.
{
 const s=base(7);eq(s,'r₁ ≤ r₂  ⇒  F(x,r₁) ≥ F(x,r₂)',65,184,1130,64,42,C.teal);
 const node=(label,x,y,w=255)=>{shape(s,x,y,w,82,C.light,C.line);text(s,label,x+10,y+10,w-20,62,25,C.navy,true,'center');};
 node('检查 F(x,0)',65,302);arrow(s,334,332,55);node('探测有限界 B 之外',403,302,310);arrow(s,730,332,55);node('二分可行 / 不可行区间',800,302,405);
 text(s,'无解：立即不可恢复',65,404,310,48,24,C.red,true);text(s,'仍可行：无穷边界',403,404,340,48,24,C.teal,true);
 text(s,'可行提高下界\n已证不可行降低上界',830,405,370,82,25,C.navy);
 line(s,65,510,1140);text(s,'UNKNOWN：保持当前边界，增加预算或带已验证方案返回',65,534,1150,50,29,C.red,true);
 text(s,'B 来自固定次序的差分约束论证；不是任意设定的“大截止时间”。',65,595,1150,40,24,C.muted);
}
// 08 — joint bound and exact symmetric subclass.
{
 const s=base(8);
 text(s,'联合必要界',65,192,520,48,30,C.teal,true);text(s,'对称子类的精确公式',680,192,530,48,30,C.teal,true);
 text(s,'m个健康腔，n=m+1片；pᵢ≥D，δᵢ≥1\nr > D 时，健康腔 + 夹爪只有 m+1 个槽位\n持片 j 放入故障腔后，才可继续取健康片',65,246,580,99,22,C.ink);
 eq(s,'取完 k 片至少需要 2k − 1 秒',65,347,580,50,31);
 eq(s,'Uⱼ = minₖ (dⱼ − 1 + q₍ₖ₎⁽⁻ʲ⁾ − 2k)',65,409,570,50,29);
 eq(s,'ρ* ≤ max(D, maxⱼ Uⱼ)',65,469,570,52,33);
 text(s,'dᵢ：源片取完期限；D=maxᵢ dᵢ\nqᵢ=pᵢ+δᵢ；按除 j 外的 q 升序取第 k 项\n异质时长下为必要界，非一般充分条件',65,531,590,103,21,C.muted);
 eq(s,'ρ* = D + p + δ − 2m − 1',680,251,550,70,37);
 text(s,'n=m+1；所有片只剩一道末工序\n源片加工完毕；机械臂空闲空爪\n共同期限 D≥2m+1；相同加工 p≥D\n相同驻留 δ≥1；所有目标腔初始为空\n每片兼容全部目标腔（含故障腔）\n取、放各1秒，移动0秒，无持片上限',680,344,540,205,22,C.ink);
 eq(s,'6 + 10 + 1 − 4 − 1 = 12 s',680,557,535,52,34,C.teal);
}
// 09 — roles and scope.
{
 const s=base(9);
 table(s,[['方法','承担的职责','当前定位'],['Simulator','离散事件执行，检查状态与动作','所有方案的物理重放'],['CP-SAT','存在性、时间安排、最短完工证明','精确数值核心'],['修复边界 / 联合判据','组织查询 / 有条件安全剪枝','v1.2.0 新增'],['FIFO / SPT / ECT 等','快速、可解释的动作选择','历史静态基线'],['MaskablePPO','在合法动作掩码下学习策略','历史强化学习路线'],['CFAR / LangGraph','预算、工具选择、反馈、记忆','研究组织与闭环控制']],65,205,1150,374,[260,570,320],23);
 text(s,'历史PPO与静态CP不支持本次故障输入，不能强行作为公平恢复基线。',65,601,1150,42,24,C.red,true);
}
// 10 — closed-loop architecture with a clearly scoped historical branch.
{
 const s=base(10);
 const node=(txt,x,y,w,h=88,fill=C.light)=>{shape(s,x,y,w,h,fill,C.line);text(s,txt,x+12,y+10,w-24,h-20,25,C.navy,true,'center');};
 node('故障状态输入\n范围与连续性检查',65,230,275);arrow(s,352,266,54);node('LangGraph\n任务管理与规划',420,230,330);arrow(s,762,266,54);node('数学优化 Skill\nCP / 边界 / 安全判据',830,230,375);
 arrow(s,1005,337,24,55,C.teal,true);
 node('保存最佳合法方案\n输出调度与数学证据',65,440,340);node('反馈分析\n调整查询、预算和目标',460,440,330);node('Simulator 独立验证\n加驻留与持片检查',845,440,360);
 shape(s,802,476,29,18,C.teal,'none','leftArrow');shape(s,416,476,29,18,C.teal,'none','leftArrow');
 shape(s,604,340,22,80,C.teal,'none','upArrow');
 text(s,'阶段七历史支路：规则策略、已有 PPO 推理\n当前故障恢复不执行这两个历史 Skill',65,565,1140,69,24,C.muted);
}
// 11 — true feedback traces.
{
 const s=base(11);
 table(s,[['实例 / 实际反馈','下一轮实际动作','最终结果'],['默认三片：r=13 无解','查询 6、9、11、12；再优化完工时间','ρ*=12 s'],['异质加工：r=12 无解','查询 6、9、10、11；再优化完工时间','ρ*=11 s'],['绕过故障腔：r=144 可行','已超过数学有限界，结束边界搜索','UNBOUNDED']],65,213,1150,250,[340,590,220],24);
 text(s,'专门的 UNKNOWN 测试',65,494,530,44,28,C.red,true);
 text(s,'同一查询 r=0：预算 0 s → UNKNOWN；预算 0.05 s → 可行，再继续搜索',65,545,1150,74,25,C.ink);
}
// 12 — project milestones and verified tag tree.
{
 const s=base(12);
 const groups=[{x:65,w:510,version:'v1.0.0',sub:'阶段一至六',lines:'1  原项目审计与独立仓库\n2  数学模型与离散事件仿真\n3  五类规则调度\n4  CP-SAT精确优化\n5  Gymnasium + MaskablePPO\n6  确定性CFAR研究反馈'},
 {x:640,w:270,version:'v1.1.0',sub:'阶段七',lines:'LangGraph工作流\nDeepSeek真实规划\n12轮实验、8轮反思'},
 {x:960,w:270,version:'v1.2.0',sub:'阶段八',lines:'故障可恢复性\n最迟修复时限\n精确重调度\n离线反馈Agent'}];
 for(const g of groups){text(s,g.version,g.x,208,g.w,62,43,C.teal,true);text(s,g.sub,g.x,275,g.w,42,25,C.muted);line(s,g.x,326,g.w-20,C.teal);text(s,g.lines,g.x,345,g.w,243,25,C.ink);}
 text(s,'v1.0.0：标签存在，无同名Release对象；v1.1.0 / v1.2.0：Release已发布。',65,602,1150,36,22,C.muted);
}
// 13 — read historical decision rows; no synthetic baseline values.
{
 const s=base(13);const rows=facts.historical_baselines;
 const val=(sc,method,policy)=>rows.filter(r=>r.scenario===sc&&r.method===method&&(!policy||r.parameters.policy===policy)).at(-1).makespan;
 const cats=['F_competition','G_dual_bottleneck'];
 chart(s,{x:65,y:205,w:780,h:420,title:'静态场景 Makespan（秒）',categories:['F 场景','G 场景'],max:240,
 series:[{name:'瓶颈规则',values:cats.map(c=>val(c,'rule','bottleneck')),fill:C.blue},
 {name:'自适应规则',values:cats.map(c=>val(c,'rule','adaptive')),fill:C.amber},
 {name:'CP-SAT',values:cats.map(c=>val(c,'cpsat')),fill:C.teal}]});
 text(s,'PPO 历史推理',890,225,330,50,28,C.teal,true);text(s,'F 场景：65 s\n模型 medium-seed-0',890,285,330,100,25,C.ink);
 text(s,'早期 CP 为 FEASIBLE\n后续增加预算取得 OPTIMAL\n最优性限于原静态编码',890,430,330,145,24,C.muted);
}
// 14 — stage 7 real LLM experiment, separate from recovery.
{
 const s=base(14);
 metric(s,'12','真实 LLM 规划轮次',65,215,280);metric(s,'8','完整有效反思',65,365,280);metric(s,'44','三组合法候选方案',65,515,280);
 chart(s,{x:385,y:205,w:830,h:410,title:'阶段七 F/G 实验活动总时间（秒）',categories:['CFAR','真实 LLM','固定流程'],max:160,
 series:[{name:'活动总时间',values:['A','B','C'].map(k=>Number(facts.stage7.arms[k].active_seconds.toFixed(3))),fill:C.blue}],legend:false,format:'0.000'});
 text(s,'三组最终均为 F=63 s、G=183 s；v1.2.0 未执行真实LLM故障恢复实验。',385,606,825,40,22,C.red,true);
}
// 15 — native editable Gantt, generated directly from saved schedule.
{
 const s=base(15);const schedule=facts.demo.schedule,scale=schedule.ticks_per_second;
 const x0=190,y0=285,unit=38,row=67;
 const colors={W1:C.blue,W2:C.teal,W3:C.amber};
 for(const [label,y] of [['机械臂',y0],['H1',y0+row],['H2',y0+2*row],['F',y0+3*row]]){text(s,label,65,y,105,40,26,C.navy,true);line(s,x0,y+43,1000);}
 for(let t=0;t<=25;t+=5){text(s,t+' s',x0+t*unit-25,235,65,35,21,C.muted,false,'center');shape(s,x0+t*unit,279,1,260,C.line);}
 for(const task of schedule.transfers){const a=task.pick_start/scale,b=task.place_end/scale;shape(s,x0+a*unit,y0,(b-a)*unit,40,colors[task.wafer_id]);text(s,task.wafer_id,x0+a*unit+3,y0+2,(b-a)*unit-6,36,20,C.white,true,'center');}
 for(const p of schedule.processes){const y=y0+row*({H1:1,H2:2,F:3}[p.chamber]);shape(s,x0+p.start/scale*unit,y,(p.end-p.start)/scale*unit,40,colors[p.wafer_id]);text(s,p.wafer_id,x0+p.start/scale*unit,y,(p.end-p.start)/scale*unit,40,22,C.white,true,'center');}
 shape(s,x0+12*unit,274,3,283,C.red);text(s,'12 s 修复',x0+12*unit-65,188,180,40,24,C.red,true);
 text(s,'机器人条含持片等待；腔室条仅表示加工，实际占用持续到取片完成。',65,565,1150,40,23,C.muted);
 text(s,'12 s：可恢复，Cmax=25 s 已证最优    13 s：已证不可恢复',65,608,1150,37,26,C.teal,true);
}
// 16 — all 9 categories plus quantitative engineering verification.
{
 const s=base(16);
 const names={symmetric_2:'对称两片',symmetric_3:'对称三片',competition_4:'四片多腔竞争',heterogeneous_p:'不同加工时间',heterogeneous_delta:'不同驻留期限',unbounded_bypass:'无穷：绕过故障腔',unbounded_mandatory:'无穷：允许持片等待',immediate_infeasible:'立即不可恢复',fractional:'精确小数刻度'};
 const selected=facts.recovery.rows.filter(r=>r.method==='cp_sat_recovery');
 table(s,[['实例（三法结论一致）','ρ* / s','剩余Cmax / s'],...selected.map(r=>[names[r.scenario],r.status==='UNBOUNDED'?'∞':r.status==='INFEASIBLE_AT_ZERO'?'空集':String(+r.rho_seconds),r.makespan_seconds?String(+r.makespan_seconds):'—'])],65,202,692,365,[382,125,185],20);
 const methods=['cp_sat_recovery','joint_exact','offline_agent'];
 const sums=methods.map(m=>facts.recovery.rows.filter(r=>r.method===m).reduce((s,r)=>s+Number(r.branches),0));
 chart(s,{x:785,y:203,w:440,h:310,title:'九类实例总 CP 分支数',categories:['基础CP','安全判据','离线Agent'],series:[{name:'分支数',values:sums,fill:C.teal}],legend:false,unit:'分支数'});
 text(s,'265 通过 / 1 跳过\n独立环境 26 通过',810,529,400,78,28,C.navy,true);
 text(s,'27 次运行；116 份方案重放通过；46 次独立穷举一致。无穷例的Cmax取 r=0。',65,610,1150,36,22,C.muted);
}
// 17 — actual file index and reproducible commands, root-relative to avoid microtype.
{
 const s=base(17);
 text(s,'根目录  D:\\SemanticaProject\\WaferSched-Agent',65,184,1150,45,27,C.teal,true);
 table(s,[['用途','以下路径均相对根目录'],['状态与仿真','src/wafer_sched/ 下：equipment.py；simulator.py；verification.py'],['静态优化与PPO','src/wafer_sched/cpsat_model.py；src/wafer_sched/rl/'],['两代Agent','src/wafer_sched/langgraph_agent/；src/wafer_sched/recovery/agent.py'],['恢复与自动测试','src/wafer_sched/recovery/；tests/wafer_sched/test_recovery.py'],['历史真实LLM实验','results/stage7_langgraph/live-study-002/'],['恢复实验与验收','results/recovery/ 下：v1.2.0-acceptance/；v1.2.0-validation/acceptance.json'],['运行说明与源码','docs/recovery.md；README.md；GitHub Release v1.2.0']],65,245,1150,307,[235,915],19);
 text(s,'在项目根目录运行：',65,572,1140,35,23,C.navy,true);
 text(s,'.venv-recovery-acceptance/Scripts/python.exe -m wafer_sched.recovery demo',65,612,1145,33,22,C.teal,false,'left','Consolas');
}
// 18 — bounded future plan, precisely three priorities.
{
 const s=base(18);
 text(s,'已知限制',65,202,430,46,30,C.red,true);
 text(s,'空故障腔，机械臂处于动作边界\n不判断故障腔内晶圆的工艺质量\n不接续执行中的不可取消动作\n未计入在线求解期间的时钟流逝\n恢复实验尚未采用真实LLM规划',65,265,475,257,25,C.ink);
 const plans=[['第一优先级  状态接续','执行中动作与复杂WIP；验收状态连续性'],['第二优先级  精确算法效率','安全判据、边界搜索、暖启动；同预算对照'],['第三优先级  真实LLM收益','接入恢复Skill；与确定性Agent公平比较']];
 for(let i=0;i<plans.length;i++){const y=204+135*i;text(s,plans[i][0],590,y,635,48,29,C.teal,true);text(s,plans[i][1],590,y+55,635,65,24,C.ink);if(i<2)line(s,590,y+122,620);}
 text(s,'计划尚未实施；当前成果不依赖“全球首次”或“已确认开放问题”的声明。',65,608,1150,40,23,C.muted);
}

await fs.mkdir(path.join(ROOT,'build'),{recursive:true});
await fs.writeFile(path.join(ROOT,'build/text_geometry.json'),JSON.stringify(boxes,null,2));
await fs.writeFile(path.join(ROOT,'build/presentation.json'),JSON.stringify(pres.toProto()));
const candidate=path.join(ROOT,'build/candidate.pptx');
await (await PresentationFile.exportPptx(pres)).save(candidate);
const finalDir=path.join(ROOT,'build/final',String(Date.now()));
await fs.mkdir(finalDir,{recursive:true});
const final=path.join(finalDir,'WaferSched-Agent_v1.2.0_项目研究汇报.pptx');
const result=await finalizePresentation({workspaceDir:ROOT,candidatePath:candidate,finalPath:final,
 pythonExecutable:path.join(runtime,'dependencies/python/python.exe'),
 integrityValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_package_integrity.py'),
 layoutValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_layout_geometry.py'),
 explicitTotalSlideCount:18,requiredNativeTableOwnerSlides:[5,6,9,11,16,17],requiredNativeChartOwnerSlides:[13,14,16],
 materializeLiteralChartWorkbooks:true,
 layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-heading-fit',
   ...[5,6,9,11,16,17].flatMap(n=>['--require-native-table-slide',String(n)])],
 fontPolicy:{basis:'design',families:[FONT,MATH,'Consolas']},verifyArtifactToolImport:true,
 receiptPath:path.join(ROOT,'qa',`presentation-validation-${path.basename(finalDir)}.json`)});
await fs.copyFile(path.join(ROOT,'qa',`presentation-validation-${path.basename(finalDir)}.json`),path.join(ROOT,'qa/presentation-validation.json'));
await fs.copyFile(final,path.join(ROOT,path.basename(final)));
console.log(JSON.stringify({final,slides:pres.slides.items.length,receipt:'qa/presentation-validation.json'}));
