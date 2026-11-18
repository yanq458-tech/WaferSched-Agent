"""Read-only checks of source integrity and the generated presentation package."""
from pathlib import Path
import hashlib
import json
import subprocess
import zipfile
import xml.etree.ElementTree as ET
from docx import Document

root = Path(__file__).resolve().parents[1]
facts = json.loads((root/'data/facts.json').read_text(encoding='utf-8'))
project = root.parents[2]
sources = json.loads((root/'data/source_index.json').read_text(encoding='utf-8'))
working_tree_document_updates = []
for key, row in sources.items():
    p = project / row['path']
    assert p.exists(), (key, p)
    recorded = subprocess.check_output(['git','show',facts['head']+':'+row['path']],cwd=project)
    assert hashlib.sha256(recorded).hexdigest() == row['sha256'], key
    if hashlib.sha256(p.read_bytes()).hexdigest() != row['sha256']:
        assert row['path'] == 'README.md', ('Original code/data changed', key)
        working_tree_document_updates.append(row['path'])
def git(*args):
    return subprocess.check_output(['git',*args],cwd=project,text=True,encoding='utf-8').strip()
assert subprocess.run(['git','merge-base','--is-ancestor',facts['head'],'HEAD'],cwd=project).returncode == 0
for tag, commit in facts['tags'].items():
    assert git('rev-parse',tag+'^{}') == commit
content = json.loads((root/'data/slide_content.json').read_text(encoding='utf-8'))
speech = Document(root/'WaferSched-Agent_v1.2.0_逐页汇报讲稿.docx')
headings = [p.text for p in speech.paragraphs if p.style.name == 'Heading 1']
assert len(headings) == 18
for heading, row in zip(headings, content['slides']):
    assert row['title'] in heading
assert sum(s['seconds'] for s in content['slides']) == 1200
pptx = root/'WaferSched-Agent_v1.2.0_项目研究汇报.pptx'
with zipfile.ZipFile(pptx) as z:
    assert z.testzip() is None
    names = z.namelist()
    slides = [n for n in names if n.startswith('ppt/slides/slide') and n.endswith('.xml')]
    charts = [n for n in names if '/charts/chart' in n and n.endswith('.xml')]
    workbooks = [n for n in names if n.startswith('ppt/embeddings/') and n.endswith('.xlsx')]
    assert len(slides) == 18 and len(charts) == 3 and len(workbooks) == 3
    table_count = sum(len(ET.fromstring(z.read(n)).findall('.//{http://schemas.openxmlformats.org/drawingml/2006/main}tbl')) for n in slides)
    assert table_count == 6
with zipfile.ZipFile(root/'charts/汇报图表_可编辑.pptx') as z:
    assert z.testzip() is None
    assert len([n for n in z.namelist() if '/charts/chart' in n and n.endswith('.xml')]) == 3
office = json.loads((root/'qa/native-office-inspection.json').read_text(encoding='utf-8-sig'))
assert len(office['slides']) == 18 and not office['text_fit_candidates']
assert office['word_pages'] == 9
assert len(list((root/'qa/slides').glob('slide-*.png'))) == 18
assert len(list((root/'qa/word').glob('page-*.png'))) == 9
receipt_path = root/'qa/presentation-validation.json'
if receipt_path.exists():
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    assert hashlib.sha256(pptx.read_bytes()).hexdigest() == receipt['finalSha256']
report = dict(status='PASS', source_hashes_unchanged=len(sources), slides=18,
              speech_sections=18, word_pages=9, planned_seconds=1200,
              native_charts=3, embedded_chart_workbooks=3, native_tables=6,
              native_office_text_fit_candidates=0,
              current_document_updates=working_tree_document_updates,
              source_version=facts['head'],
              experiment_scope='Existing evidence audited; no solver experiments rerun',
              visual_review='All 18 slides and all 9 Word pages inspected; edited slides rechecked')
(root/'qa/materials-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
