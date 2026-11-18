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
const facts=JSON.parse(await fs.readFile(path.join(ROOT,'sources/evidence.json'),'utf8'));
const content=JSON.parse(await fs.readFile(path.join(ROOT,'sources/content.json'),'utf8'));
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

const BUILD=path.join(ROOT,'build',String(Date.now()));
const captions=[
 '已发布版本 v1.3.0', 'Qiao 等（2015） · Kim 等（2016） · 袁凤莲等（2023）', 'boundary.py · docs/recovery-v1.3.md',
 'continuation.py · docs/recovery-v1.3.md', 'model.py · solver.py', 'boundary.py · replay.py · primitive_oracle.py',
 'agent.py · dispatch.py · sealed/agent.json', 'mid_pick/baseline-postcheck.json · enumeration.json',
 'evacuate、sealed 的输入与 comparison.csv', 'comparison.csv · summary.json · enumeration.json · recovery-tests.xml', 'docs/recovery-v1.3.md'];
function page(i){
 const s=pres.slides.add();s.background.fill=C.white;
 const c=content[i-1];
 shape(s,0,0,1280,8,C.teal);
 text(s,c.title,64,46,1152,68,42,C.navy,true);
 text(s,c.subtitle,65,119,1150,40,24,C.muted);
 line(s,65,661,1150,C.line);
 text(s,captions[i-1],65,668,1080,30,14,C.muted);
 text(s,String(i).padStart(2,'0'),1162,668,53,30,16,C.muted,false,'right');
 s.speakerNotes.text=c.speech+'\n\n资料：'+c.source;
 return s;
}
function tag(s,label,x,y,w=350){text(s,label,x,y,w,42,28,C.teal,true);}
function note(s,str,y=599){shape(s,65,y,1150,46,'#E2F1EF');text(s,str,82,y+4,1115,38,21,C.navy);}
function node(s,label,x,y,w,h=74,fill='#E4F1EF'){shape(s,x,y,w,h,fill);text(s,label,x+9,y+4,w-18,h-8,24,C.navy,true,'center');}

{
 const s=pres.slides.add();s.background.fill=C.navy;
 shape(s,62,84,69,6,'#80D5CB');
 text(s,'WaferSched-Agent  v1.3.0',64,109,1145,42,26,'#A8DED7',true);
 text(s,'单臂多腔设备的故障恢复',61,196,1160,131,66,C.white,true);
 text(s,'可恢复性判定 · 最迟修复时限 · 精确重调度',67,351,1130,60,32,'#D4E4EF');
 line(s,66,500,1148,'#7294A6');
 text(s,'计算数学与智能体交叉研究',66,526,1130,57,26,C.white);
 text(s,'从故障快照生成可复查的合法调度',67,588,1130,47,22,'#B0CAD8');
 s.speakerNotes.text=content[0].speech+'\n\n资料：'+content[0].source;
}
{
 const s=page(2);
 const refs=[
  ['Qiao 等 · IEEE T-ASE · 2015','Petri 网刻画单臂组合设备，提出工艺腔故障响应策略。'],
  ['Kim 等 · IEEE T-ASE · 2016','研究时间变化与驻留约束下的非周期可调度性。'],
  ['袁凤莲等 · 自动化学报 · 2023','梳理组合设备、晶圆流与 Petri 网建模调度方法。']
 ];
 refs.forEach(([a,b],i)=>{
  const y=188+109*i;
  text(s,a,66,y,1148,42,25,C.teal,true);
  text(s,b,66,y+45,1145,40,24,C.ink);
  if(i<2)line(s,65,y+94,1150);
 });
 note(s,'本项目计算具体快照的可恢复性及维修边界。一般故障与现场闭环仍待研究。',572);
}
{
 const s=page(3);
 eq(s,'F(x, r) = 1  ⇔  ∃ σ ∈ S(x, r)',70,208,690,68,49);
 eq(s,'ρ*(x) = sup { r ≥ 0 : F(x, r) = 1 }',70,302,720,67,45);
 eq(s,'min  Cₘₐₓ(σ)   s.t.   σ ∈ S(x, r)',70,395,720,69,42);
 line(s,68,495,715);
 text(s,'有限边界 · 无有限上界 · 立即修复仍无解',69,518,720,52,24,C.teal,true);
 shape(s,825,207,389,367,'#E9F2F6');
 text(s,'x   故障快照与工艺策略\nr   自故障起的修复延迟\nσ   剩余操作的调度\nS   合法的剩余调度集合\nCₘₐₓ   最后一片的出片时刻',850,232,342,315,25,C.ink);
}
{
 const s=page(4);
 tag(s,'v1.2.0',68,198,208);text(s,'动作边界起算 · 故障腔为空',276,199,937,42,23);
 tag(s,'v1.3.0',68,255,208);text(s,'动作中途可接续 · 已完工占片按授权处理',276,256,937,42,23);
 line(s,65,320,1150);
 const x1=92,x2=572,x3=1177;
 shape(s,x1,409,x2-x1,44,'#BADCD7');shape(s,x2,409,x3-x2,44,'#D6E6F0');
 text(s,'执行已承诺动作，工艺时钟继续累计',x1+6,411,x2-x1-12,39,23,C.navy,true,'center');
 text(s,'CP-SAT 优化剩余调度',x2+8,411,x3-x2-16,39,23,C.navy,true,'center');
 text(s,'0  故障',x1,369,180,35,21,C.navy,true);
 text(s,'h  可调度',x2-35,369,180,35,21,C.navy,true);
 text(s,'完成',x3-62,369,85,35,21,C.navy,true);
 eq(s,'h = max{ tᵣₑₘ, τ }          r′ = max{0, r − h}',96,486,1057,64,38);
 text(s,'tᵣₑₘ 为剩余动作时长，τ 为派发延迟，r′ 为后缀修复延迟。',96,570,1110,44,22,C.muted);
}
{
 const s=page(5);
 table(s,[
 ['约束','在模型中的作用'],
 ['工艺与资源','候选腔、工序先后、机械臂互斥、腔室容量'],
 ['驻留与持片','取完 − 加工完 ≤ 驻留上限   |   放完 − 取完 ≤ 持片上限'],
 ['维修与占片','故障腔放片开始 ≥ r′   |   封闭策略下故障腔取片开始 ≥ r′'],
 ['优化目标','在给定 r′ 下，最小化最后一片晶圆的出片时刻']
 ],65,195,1150,361,[238,912],24);
 note(s,'时间采用精确整数刻度。有限边界处用同一模型再求最短剩余完工时间。',585);
}
{
 const s=page(6);
 tag(s,'边界搜索',68,187,330);tag(s,'独立核验',692,187,390);
 shape(s,649,202,2,374,C.line);
 eq(s,'F(x, r₂) ≤ F(x, r₁)    (r₁ ≤ r₂)',68,239,568,61,34);
 text(s,'立即修复 → 证明的有限上探点 → 二分',68,324,570,46,23,C.navy,true);
 text(s,'未知查询保留原有界与合法见证。提早修复只放宽约束，既有方案仍可等待。',68,387,550,108,23);
 text(s,'Simulator 全程重放',692,256,487,43,27,C.navy,true);
 text(s,'检查原语顺序、驻留和持片时钟。',692,303,502,46,22);
 text(s,'小规模原语最短路',692,386,491,43,27,C.navy,true);
 text(s,'独立枚举可行性与最短完工时间。',692,433,502,47,22);
 note(s,'有限时点已可行且下一精确刻度不可行，才在该搜索区间内认证边界。',568);
}
{
 const s=page(7);
 const xs=[65,362,659,956], w=259;
 const phases=['故障快照\\n历史一致性检查','离线 LangGraph\\n调度搜索与预算','CP-SAT\\n可行性与最短完工','Simulator\\n全程重放验证'];
 phases.forEach((p,i)=>{node(s,p.replace('\\n','\n'),xs[i],222,w);if(i<3)arrow(s,xs[i]+w+7,249,24,17);});
 text(s,'求解状态与见证反馈给智能体，由它选择下一次查询或优化目标。',69,325,1145,45,24,C.ink);
 line(s,65,387,1150);
 tag(s,'封闭腔案例的真实查询片段',68,420,790);
 const steps=['4 秒 不可行','2 秒 可行','3 秒 可行','固定 3 秒求最短完工'];
 steps.forEach((q,i)=>{node(s,q,xs[i],480,w,61,i===0?'#F5E5E0':'#E4F1EF');if(i<3)arrow(s,xs[i]+w+7,502,24,17);});
 text(s,'边界收紧后使用已验证方案作时间提示。',68,571,1130,43,22,C.muted);
}
{
 const s=page(8);
 const model=facts.mid_pick;
 const sx=195, w=1000, map=t=>sx+t*w/25, y=280;
 const rows=['W2','W1','故障腔 F'];
 for(let i=0;i<3;i++){
   text(s,rows[i],68,y+i*90,119,43,25,C.navy,true);
   line(s,sx,y+60+i*90,w,C.line);
 }
 for(const t of [0,5,10,15,20,25]) {
   shape(s,map(t),226,1,300,C.line);text(s,String(t),map(t)-15,531,38,35,17,C.muted,false,'center');
 }
 text(s,'故障后时间（秒）',883,570,312,37,20,C.muted,false,'right');
 function bar(row,start,end,label,fill,color=C.navy){
   const x=map(start),width=map(end)-x;
   shape(s,x,y+row*90,width,44,fill);
   if(label) text(s,label,x+2,y+row*90,width-4,44,20,color,true,'center');
 }
 bar(0,0,model.pick_end,'',C.teal);
 bar(0,model.w2_load,model.w2_end,'健康腔加工','#B7DBD6');
 bar(1,model.w1_pick,model.repair,'机械臂持片等待','#C8DDEC');
 bar(1,model.w1_load,model.w1_end,'故障腔加工','#B7DBD6');
 bar(2,0,model.repair,'维修期间不可放片','#F2DCD6');
 bar(2,model.repair,24.5,'恢复可用','#D7E8F3');
 shape(s,map(model.repair)-1,222,3,301,C.red);
 text(s,'11.5 秒修复',map(model.repair)-173,179,162,35,20,C.red,true,'right');
 text(s,'0.5 秒完成已开始的取片',sx,232,370,36,20,C.teal,true);
 text(s,'24.5 秒出片',1028,339,168,31,19,C.teal,true,'right');
 note(s,'时间轴为关键区段，取放与卸片见完整日志。12 秒修复不可行。',600);
}
{
 const s=page(9);
 table(s,[
 ['故障腔 S2 内已完工晶圆','允许维修期间取出','封闭到修复后取出'],
 ['最早取片规则','可在维修期间取片','取片开始 ≥ 修复时刻'],
 ['驻留期限','继续累计','继续累计'],
 ['最迟修复时限','无有限上界','3 秒'],
 ['最短剩余完工时间','16 秒（立即修复）','17 秒（边界处）']
 ],65,202,1150,350,[389,379,382],24);
 note(s,'只改变工艺策略。两种策略均要求工艺方确认等待和撤离条件。',583);
}
{
 const s=page(10);
 const f=facts.summary;
 metric(s,String(f.runs),'对照运行',73,185,250);
 metric(s,String(f.verified_postchecks),'全程重放核验',350,185,250);
 metric(s,String(f.oracle_agreements),'独立枚举一致',627,185,250);
 metric(s,String(facts.tests),'故障恢复测试通过',907,185,280);
 chart(s,{x:65,y:321,w:660,h:290,title:'边界流程查询数',categories:['三片对称例','取片途中'],series:[
  {name:'基础精确方法',values:facts.comparison.map(c=>c.base_queries),fill:C.blue},
  {name:'增强精确方法',values:facts.comparison.map(c=>c.enhanced_queries),fill:C.teal}],max:18,unit:'次数'});
 tag(s,'查询减少，分支未必减少',751,330,455);
 text(s,'三片对称例\n分支数 '+facts.comparison[0].base_branches+' → '+facts.comparison[0].enhanced_branches+
  '\n\n取片途中\n两种方法均为 '+facts.comparison[1].base_branches+' 个分支',753,381,445,181,23);
 text(s,'常规对照 '+f.queries+' 次查询，UNKNOWN 为 '+f.unknown_queries+'。',753,572,449,52,20,C.muted);
}
{
 const s=page(11);
 tag(s,'当前边界',65,188,283);
 text(s,'单设备、单故障、确定时长、完整可重放历史。腔内加工中断、向故障腔放片和复合命令中断仍超出模型。',67,242,1145,83,24);
 line(s,65,338,1150);
 const plans=[
 ['01','补齐故障规则','联合工艺方明确中止、封闭、撤离和质量判定规则。'],
 ['02','扩大算例与对照','在相同预算下比较约束剪枝、边界搜索和提示贡献。'],
 ['03','验证在线接续','接入设备时钟和日志，验证求解后指令仍可按时派发。']
 ];
 plans.forEach(([n,a,b],i)=>{
  const y=362+87*i;
  text(s,n,66,y,57,53,27,C.teal,true);
  text(s,a,139,y,235,53,27,C.navy,true);
  text(s,b,381,y,829,53,23,C.ink);
 });
}
await fs.mkdir(path.join(BUILD,'deliver'),{recursive:true});
const candidate=path.join(BUILD,'candidate.pptx');
await (await PresentationFile.exportPptx(pres)).save(candidate);
const final=path.join(BUILD,'deliver','WaferSched-Agent_v1.3.0_研究汇报.pptx');
await finalizePresentation({workspaceDir:ROOT,candidatePath:candidate,finalPath:final,
 pythonExecutable:path.join(runtime,'dependencies/python/python.exe'),
 integrityValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_package_integrity.py'),
 layoutValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_layout_geometry.py'),
 explicitTotalSlideCount:11,requiredNativeTableOwnerSlides:[5,9],requiredNativeChartOwnerSlides:[10],
 materializeLiteralChartWorkbooks:true,
 layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-heading-fit','--require-native-table-slide','5','--require-native-table-slide','9'],
 fontPolicy:{basis:'design',families:[FONT,MATH]},verifyArtifactToolImport:true,
 receiptPath:path.join(BUILD,'validation.json')});
await fs.copyFile(final,path.join(ROOT,path.basename(final)));
console.log(JSON.stringify({slides:pres.slides.items.length,chart:10}));
