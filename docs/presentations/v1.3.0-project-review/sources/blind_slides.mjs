// Import the actual local deck to inherit its editable slide style and dimensions.
// The packager transfers only the three new slides, preserving original slide parts.
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';

const [base, data, out] = process.argv.slice(2);
const rt = process.env.CODEX_RUNTIME || path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime');
const req = createRequire(path.join(rt,'dependencies/node/node_modules/__runtime__.cjs'));
const {FileBlob, PresentationFile} = await import(pathToFileURL(req.resolve('@oai/artifact-tool')).href);
const deck = await PresentationFile.importPptx(await FileBlob.load(base));
if (deck.slides.items.length !== 17) throw Error('Expected the 17-slide presentation');
const docs = JSON.parse(await fs.readFile(data,'utf8'));
const navy='#17324D', teal='#007F78', ink='#162B3F', muted='#586B7D', edge='#CED9E2';
function rect(s,x,y,w,h,fill){
  return s.shapes.add({geometry:'rect',position:{left:x,top:y,width:w,height:h},fill,line:{fill:'none',width:0}});
}
function text(s,label,x,y,w,h,size,color,bold=false,alignment='left'){
  const sh=rect(s,x,y,w,h,'none');sh.text=label;
  sh.text.style={typeface:'Microsoft YaHei',fontSize:size,bold,color,alignment,verticalAlignment:'middle',insets:0,autoFit:'none',wrap:'square'};
}
for(const [i,p] of docs.entries()){
  const s=deck.slides.add();s.background.fill='#FFFFFF';
  rect(s,0,0,1280,8,teal);
  text(s,p.title,64,46,1160,68,40,navy,true);
  text(s,p.sub,65,118,1150,38,23,muted);
  const t=s.tables.add({rows:p.rows.length,columns:p.columns.length,left:65,top:p.y,width:1150,height:p.h,columnWidths:p.columns,values:p.rows});
  t.borders.assign({fill:edge,width:1,style:'solid'});
  for(let r=0;r<p.rows.length;r++)for(let c=0;c<p.columns.length;c++){
    const cell=t.getCell(r,c);
    cell.fill=r===0?navy:(r%2?'#FFFFFF':'#F2F6F8');
    cell.text.style={typeface:'Microsoft YaHei',fontSize:i===1?22:23,bold:r===0,color:r===0?'#FFFFFF':ink,verticalAlignment:'middle',insets:8};
  }
  if(i===0){
    text(s,p.extra[0],65,460,1150,40,25,teal,true);text(s,p.extra[1],65,510,1150,63,25,ink);
  }else if(i===1){
    text(s,'“未找到”表示预算内尚无通过重放的方案；已证上界仍然有效。',65,563,1160,62,23,ink);
  }else{
    for(let j=0;j<2;j++){
      text(s,p.extra[j*2],65,395+83*j,200,62,24,teal,true);
      text(s,p.extra[j*2+1],274,395+83*j,938,62,23,ink);
    }
    text(s,'反序复测时，1 秒内 Agent 相对固定组合的优势由 2 例缩为 1 例。',65,571,1150,50,23,muted);
  }
  rect(s,65,661,1150,1.3,edge);text(s,p.foot,65,668,1060,30,14,muted);
  text(s,String(17+i),1162,668,53,30,16,muted,false,'right');
  s.speakerNotes.text=p.speech.join('\n\n')+'\n\n资料：'+p.source;
}
await (await PresentationFile.exportPptx(deck)).save(out);
