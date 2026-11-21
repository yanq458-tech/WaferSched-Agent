"""Extract reviewed evidence and build the short talk's Chinese speaker script."""
import csv
import json
from pathlib import Path
import re
from xml.etree import ElementTree

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

source = Path(__file__).resolve().parent
output = source.parent
repository = output.parents[2]
archive = repository / "results/recovery/v1.3.0-acceptance"

def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def write(path, content):
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def check_evidence():
    with (archive / "comparison.csv").open(encoding="utf-8", newline="") as stream:
        rows = {(row["case"], row["method"]): row for row in csv.DictReader(stream)}
    summary = read(archive / "summary.json")
    assert read(archive / "acceptance.json")["study"] == summary
    assert len(rows) == summary["runs"] == 42
    assert len({case for case, _ in rows}) == summary["cases"] == 14
    assert sum(int(row["queries"]) for row in rows.values()) == summary["queries"] == 287
    assert sum(int(row["unknown_queries"]) for row in rows.values()) == summary["unknown_queries"] == 0
    assert sum(row["verified"] == "True" for row in rows.values()) == summary["verified_postchecks"] == 30
    oracle = read(archive / "enumeration.json")
    assert len(oracle) == summary["oracle_agreements"] == 27
    assert all(row["agree"] and row["status"] == row["cp"] for row in oracle)
    suite = ElementTree.parse(archive / "recovery-tests.xml").find(".//testsuite")
    assert suite is not None and suite.attrib["tests"] == "42"
    assert all(suite.attrib[field] == "0" for field in ("failures", "errors", "skipped"))
    example = read(archive / "mid_pick/baseline-postcheck.json")
    start = example["prefix"]["fault_time"]
    offset = example["prefix"]["offset"]
    schedule = example["best"]["schedule"]
    scale = schedule["ticks_per_second"]
    relative = lambda tick: offset + tick / scale
    processes = {row["wafer_id"]: row for row in schedule["processes"]}
    transfer = next(row for row in schedule["transfers"] if row["wafer_id"] == "W1" and row["destination"] == "F")
    assert start == 5.5 and offset == .5
    assert example["verification_valid"] and example["makespan_optimal"]
    assert example["witness_repair_delay_seconds"] == 11.5 and example["makespan_seconds"] == 24.5
    assert any(
        row["case"] == "mid_pick" and row["repair"] == 12 and row["status"] == "INFEASIBLE"
        for row in oracle
    )
    evacuate, sealed = (read(archive / name / "input.json") for name in ("evacuate", "sealed"))
    assert evacuate.pop("policy") == "evacuate_finished"
    assert sealed.pop("policy") == "sealed_finished"
    assert evacuate == sealed
    assert rows["evacuate", "baseline"]["status"] == "UNBOUNDED"
    assert float(rows["evacuate", "baseline"]["makespan_seconds"]) == 16
    assert float(rows["sealed", "baseline"]["rho_seconds"]) == 3
    assert float(rows["sealed", "baseline"]["makespan_seconds"]) == 17
    trace = read(archive / "sealed/agent.json")
    end = trace["suffix_search"]["history"][-4:]
    assert [(row["proposal"]["query_tick"], row["result"]["status"]) for row in end] == [
        (4, "INFEASIBLE"), (2, "OPTIMAL"), (3, "OPTIMAL"), (3, "OPTIMAL")
    ]
    assert end[-1]["proposal"]["phase"] == "optimize" and end[-1]["result"]["verified_time_hint"]
    comparison = []
    for case in ("three", "mid_pick"):
        base, enhanced = (rows[case, method] for method in ("baseline", "enhanced"))
        comparison.append({
            "case": case, "base_queries": int(base["queries"]), "enhanced_queries": int(enhanced["queries"]),
            "base_branches": int(base["branches"]), "enhanced_branches": int(enhanced["branches"])
        })
    assert [(r["base_queries"], r["enhanced_queries"], r["base_branches"], r["enhanced_branches"])
            for r in comparison] == [(15, 7, 1265, 1337), (14, 14, 47, 47)]
    return {
        "archive": "results/recovery/v1.3.0-acceptance",
        "summary": summary, "tests": int(suite.attrib["tests"]), "comparison": comparison,
        "mid_pick": {
            "pick_end": offset, "repair": example["witness_repair_delay_seconds"],
            "w2_load": relative(processes["W2"]["start"]), "w2_end": relative(processes["W2"]["end"]),
            "w1_pick": relative(transfer["pick_end"]), "w1_load": relative(processes["W1"]["start"]),
            "w1_end": relative(processes["W1"]["end"]), "makespan": example["makespan_seconds"],
        },
        "references": [
            {"doi": "10.1109/TASE.2014.2312823", "source": "https://digitalcommons.njit.edu/fac_pubs/6930/"},
            {"doi": "10.1109/TSMC.2020.2964032", "source": "https://digitalcommons.njit.edu/fac_pubs/3711/"},
            {"doi": "10.1109/TASE.2016.2531105", "source": "https://pure.kaist.ac.kr/en/publications/schedulability-analysis-for-noncyclic-operation-of-time-constrain/"},
            {"doi": "10.1109/TASE.2025.3554273", "source": "https://doi.org/10.1109/TASE.2025.3554273"},
            {"doi": "10.16383/j.aas.c210951", "source": "https://www.aas.net.cn/cn/article/doi/10.16383/j.aas.c210951"},
        ],
    }

evidence = check_evidence()
write(source / "evidence.json", evidence)
slides = read(source / "content.json")
han_count = sum(len(re.findall(r"[\u3400-\u9fff]", item["speech"])) for item in slides)
duration = sum(item["seconds"] for item in slides)
assert len(slides) == 17 and 1100 <= han_count <= 1400 and 480 <= duration <= 600
document = Document()
section = document.sections[0]
section.page_width, section.page_height = Cm(21), Cm(29.7)
section.top_margin = section.bottom_margin = Cm(2.1)
section.left_margin = section.right_margin = Cm(2.25)
for name, size in (("Normal", 12), ("Title", 24), ("Heading 1", 15)):
    style = document.styles[name]
    style.font.name, style.font.size = "Microsoft YaHei", Pt(size)
    style.font.color.rgb = RGBColor.from_string("000000")
    for border in style.element.xpath("./w:pPr/w:pBdr"):
        border.getparent().remove(border)
    style.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
body = document.styles["Normal"].paragraph_format
body.line_spacing = Pt(19)
body.space_after = Pt(12)
body.keep_together = True
heading = document.styles["Heading 1"].paragraph_format
heading.space_before = Pt(9)
heading.space_after = Pt(7)
heading.keep_with_next = True
document.add_paragraph("WaferSched-Agent v1.3.0 研究汇报", style="Title")
sub = document.add_paragraph(f"逐页讲稿　{len(slides)} 张幻灯片　正文 {han_count} 个汉字　目标 {duration//60} 分 {duration%60:02d} 秒")
sub.paragraph_format.space_after = Pt(18)
sub.runs[0].font.size = Pt(10)
sub.runs[0].font.color.rgb = RGBColor.from_string("536674")
elapsed = 0
for index, item in enumerate(slides, start=1):
    elapsed += item["seconds"]
    title = document.add_paragraph(f"{index:02d}　{item['title']}", style="Heading 1")
    if index in (6, 12):
        title.paragraph_format.page_break_before = True
    time = title.add_run(f"　{item['seconds']} 秒 · 累计 {elapsed//60:02d}:{elapsed%60:02d}")
    time.font.color.rgb = RGBColor.from_string("536674")
    time.font.size = Pt(9)
    document.add_paragraph(item["speech"])
document.core_properties.title = "WaferSched-Agent v1.3.0 逐页讲稿"
document.core_properties.author = "WaferSched-Agent"
footer = section.footer.paragraphs[0]
footer.alignment = 2
footer.add_run("WaferSched-Agent v1.3.0  /  ")
field = OxmlElement("w:fldSimple")
field.set(qn("w:instr"), "PAGE")
footer._p.append(field)
document.save(output / "WaferSched-Agent_v1.3.0_逐页讲稿.docx")
print(json.dumps({"slides": len(slides), "han_body": han_count, "seconds": duration}))
