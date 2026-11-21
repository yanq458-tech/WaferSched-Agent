"""Reproduce the blind-study update from the preserved local 17-slide / long-script checkpoint."""
import hashlib
import json
import os
from pathlib import Path
from copy import deepcopy
import subprocess
from tempfile import TemporaryDirectory
from zipfile import ZipFile, ZIP_DEFLATED

from docx import Document
from docx.text.paragraph import Paragraph
from lxml import etree as ET

SOURCE = Path(__file__).resolve().parent
OUT = SOURCE.parent
REPO = OUT.parents[2]
ARCHIVE = REPO / "results/recovery/feedback-study/final-holdout"
BASE = "6c9eeb49e118360fd7885e3f08040cc90c2729da"
PPT = "WaferSched-Agent_v1.3.0_研究汇报.pptx"
DOC = "WaferSched-Agent_v1.3.0_逐页讲稿.docx"
RUNTIME = Path(os.environ.get("CODEX_RUNTIME", Path.home() / ".cache/codex-runtimes/codex-primary-runtime"))
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG = "{http://schemas.openxmlformats.org/package/2006/relationships}"
CT = "{http://schemas.openxmlformats.org/package/2006/content-types}"


def read(path):
    return json.loads(path.read_bytes())


def reviewed_pages():
    pages = read(SOURCE / "blind_review.json")
    methods = ["fixed", "plain", "agent"]
    manifest = read(ARCHIVE / "manifest.json")
    assert len(manifest) == 18
    counts = []
    for budget in (1, 30):
        groups = {}
        for method in methods:
            groups[method] = {}
            for item in manifest:
                name = item["case"]
                assert hashlib.sha256((ARCHIVE / "inputs" / (name + ".json")).read_bytes()).hexdigest() == item["sha256"]
                groups[method][name] = read(ARCHIVE / f"b{budget}" / name / f"0-{method}.json")["metrics"]
        proofs = {k: {n for n, v in rows.items() if v["status"] in {"FINITE", "INFEASIBLE_AT_ZERO", "UNBOUNDED"}} for k, rows in groups.items()}
        assert proofs["plain"] == proofs["agent"]
        if budget == 1:
            assert proofs["agent"] - proofs["fixed"] == {"blind-16-m-f1", "blind-16-m-f3"} and not proofs["fixed"] - proofs["agent"]
        else:
            assert proofs["fixed"] == proofs["agent"]
        counts.append([f"{budget} 秒", *[f"{len(proofs[k])} / 18" for k in methods]])
    agent = groups["agent"]
    unknown = [[n, "未找到" if v["lower"] is None else f'{v["lower"]:g}', f'{v["upper"]:g}']
               for n, v in sorted(agent.items()) if v["status"] == "UNKNOWN"]
    infeasible = [n for n, v in sorted(agent.items()) if v["status"] == "INFEASIBLE_AT_ZERO"]
    finite = [n for n,v in agent.items() if v["status"] == "FINITE"]
    assert len(finite) == 9 and all("-m-" in n for n in finite) and len(unknown) == 7
    assert infeasible == ["blind-20-h-f1", "blind-24-h-f3"]
    for n in infeasible:
        c = read(ARCHIVE/"b30"/n/"0-agent.json")["evidence"]["certificate"]
        assert c["kind"] == "exclusive_terminal_deadlines" and c["min_excess_tick"] > 0
    assert agent["blind-16-m-f1"]["rho"] == 86.75
    assert [r for r in unknown if r[1] != "未找到"] == [["blind-16-h-f3","4.625","42.25"]]
    pages[0]["rows"] = [["30 秒首轮结论", "例数", "证据"], ["有限维修边界", str(len(finite)), "9 个中竞争例：合法调度达到已证上界。"],
                         ["即刻修复也无解", str(len(infeasible)), "blind-20-h-f1、blind-24-h-f3：同腔竞争必然超期。"],
                         ["尚未判定",str(len(unknown)),"7 个高竞争例：现有证据不足以闭合边界。"]]
    pages[1]["rows"] = [["快照编号", "已验可行下界（秒）", "已证上界（秒）"], *unknown]
    pages[2]["rows"] = [["每例预算","固定工具组合","同策略普通函数","离线 LangGraph Agent"], *counts]
    return pages


def package(deck, candidate, dest, pages):
    # Only copy the new slides and notes. Keep every original layout, chart,
    # embedded workbook and drawing part from the real local PowerPoint file.
    with ZipFile(deck) as old, ZipFile(candidate) as added:
        parts = {k:old.read(k) for k in old.namelist()}
        pres = ET.fromstring(parts["ppt/presentation.xml"])
        ids = pres.find(P+"sldIdLst")
        rels = ET.fromstring(parts["ppt/_rels/presentation.xml.rels"])
        types = ET.fromstring(parts["[Content_Types].xml"])
        for i, page in enumerate(pages):
            n = 18+i
            slide = f"ppt/slides/slide{n}.xml"
            notes = f"ppt/notesSlides/notesSlide{n}.xml"
            for target, template in ((slide, "ppt/slides/slide17.xml"), (notes, "ppt/notesSlides/notesSlide17.xml")):
                parts[target] = added.read(target)
                ct = types.find(f"{CT}Override[@PartName='/{template}']")
                ET.SubElement(types, CT+"Override", PartName="/"+target, ContentType=ct.get("ContentType"))
            assert page["title"] in ET.fromstring(parts[slide]).itertext()
            assert not ET.fromstring(parts[slide]).xpath('//@r:embed|//@r:link|//@r:id',namespaces={'r':R[1:-1]})
            for folder, stem in (("slides","slide"), ("notesSlides","notesSlide")):
                base = f"ppt/{folder}/_rels/{stem}17.xml.rels"
                relation = ET.fromstring(parts[base])
                for entry in relation:
                    for kind in ("slide","notesSlide"):
                        if entry.get("Type").endswith("/"+kind):
                            entry.set("Target", entry.get("Target").replace("17.xml",f"{n}.xml"))
                parts[base.replace("17.xml",f"{n}.xml")] = ET.tostring(relation,encoding="UTF-8")
            rid = f"rBlindReview{n}"
            ET.SubElement(rels, PKG+"Relationship", Id=rid, Type=R[1:-1]+"/slide", Target="/"+slide)
            link = ET.Element(P+"sldId",id=str(max(int(e.get("id")) for e in ids)+1))
            link.set(R+"id",rid)
            ids.insert(len(ids)-1,link)
        last = ET.fromstring(parts["ppt/slides/slide17.xml"])
        label = [e for e in last.iter(A+"t") if e.text == "17"]
        assert len(label) == 1
        label[0].text = "20"
        for key, root in (("ppt/presentation.xml",pres),("ppt/_rels/presentation.xml.rels",rels),("[Content_Types].xml",types),("ppt/slides/slide17.xml",last)):
            parts[key] = ET.tostring(root,encoding="UTF-8",xml_declaration=True)
        app = ET.fromstring(parts["docProps/app.xml"])
        for key in ("Slides","Notes"):
            elem = app.find("{*}"+key)
            if elem is not None:
                elem.text = "20"
        parts["docProps/app.xml"] = ET.tostring(app,encoding="UTF-8")
        with ZipFile(dest,"w",compression=ZIP_DEFLATED) as z:
            for k,v in parts.items():
                z.writestr(k,v)


def manuscript(base, out, pages):
    doc = Document(base)
    sub = doc.paragraphs[1]
    assert "17 张" in sub.text
    sub.runs[0].text = "20 张幻灯片 · 完整讲解约 23 分钟 · 小字为换页计时提示"
    anchor = next(p for p in doc.paragraphs if p.text.startswith("17　三个后续研究方向"))
    anchor.runs[0].text = "20　三个后续研究方向"
    anchor.runs[1].text = "　65 秒 · 累计 23:08"
    elapsed = 19*60+3
    for number,p in enumerate(pages,17):
        elapsed += p["seconds"]
        clone = deepcopy(anchor._p)
        anchor._p.addprevious(clone)
        title = Paragraph(clone, anchor._parent)
        title.runs[0].text = f"{number:02d}　{p['title']}"
        title.runs[1].text = f"　{p['seconds']} 秒 · 累计 {elapsed//60:02}:{elapsed%60:02}"
        title.paragraph_format.page_break_before = number == 18
        for paragraph in p["speech"]:
            anchor.insert_paragraph_before(paragraph, style="Normal")
        if number == 18:
            values = [f"{name}［{lo}，{hi}］" for name,lo,hi in p["rows"][1:]]
            cue = anchor.insert_paragraph_before("讲者备查（秒）　" + "；".join(values) + "。", style="Normal")
            from docx.shared import Pt, RGBColor
            cue.runs[0].font.size = Pt(10)
            cue.runs[0].font.color.rgb = RGBColor.from_string("536674")
    doc.save(out)


def main():
    pages = reviewed_pages()
    work = OUT / "build"
    work.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=work) as workspace:
        tmp = Path(workspace)
        for name in (PPT,DOC):
            rel = (OUT/name).relative_to(REPO).as_posix()
            (tmp/name).write_bytes(subprocess.check_output(["git","show",f"{BASE}:{rel}"],cwd=REPO))
        data = tmp/"sections.json"
        data.write_text(json.dumps(pages,ensure_ascii=False),encoding="utf8")
        candidate = tmp/"candidate.pptx"
        node = RUNTIME/"dependencies/node/bin"/("node.exe" if os.name=="nt" else "node")
        subprocess.run([node,SOURCE/"blind_slides.mjs",tmp/PPT,data,candidate],check=True)
        package(tmp/PPT,candidate,tmp/"updated.pptx",pages)
        manuscript(tmp/DOC,tmp/"updated.docx",pages)
        (tmp/"updated.pptx").replace(OUT/PPT)
        (tmp/"updated.docx").replace(OUT/DOC)


if __name__ == "__main__":
    main()
