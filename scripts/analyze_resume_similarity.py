"""Read-only comparison of Gecko Main DOCX resume wording."""

from collections import Counter, defaultdict
from datetime import datetime
from itertools import combinations
from pathlib import Path
import csv
import hashlib
import json
import re
import sys

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'job-scout'))
import resume_naming
SOURCE = ROOT / "output" / "resumes"
DEST = ROOT / "reports" / "resume-similarity"
HEADINGS = {
    "PROFESSIONAL SUMMARY": "Summary",
    "CORE STRENGTHS": "Strengths",
    "SELECTED RESULTS": "Results",
    "PROFESSIONAL EXPERIENCE": "Experience",
    "TOOLS & PLATFORMS": "Tools",
    "EDUCATION & CERTIFICATIONS": "Education",
}
TAILORED = ("Summary", "Strengths", "Results", "Experience", "Tools")


def normalize(value):
    return " ".join(re.findall(r"[\w]+(?:['’][\w]+)?", value.casefold()))


def shingles(value):
    words = normalize(value).split()
    return set(zip(*(words[i:] for i in range(4)))) if len(words) >= 4 else set()


def read_resume(path):
    doc = Document(path)
    sections = defaultdict(list)
    all_text = []
    current = "Header"
    for item in doc.iter_inner_content():
        if isinstance(item, Paragraph):
            value = item.text.strip()
            if not value:
                continue
            if value.upper() in HEADINGS:
                current = HEADINGS[value.upper()]
                continue
            sections[current].append(value)
            all_text.append(value)
        elif isinstance(item, Table):
            for row in item.rows:
                values = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if values:
                    value = " | ".join(values)
                    sections[current].append(value)
                    all_text.append(value)
    stat = path.stat()
    stem = path.stem.split("+")
    return {
        "file": path.name,
        "company": stem[1].replace("-", " ") if len(stem) > 2 else "",
        "role": stem[2].replace("-", " ") if len(stem) > 3 else "",
        "job_id": resume_naming.job_number(path) if len(stem) > 2 else "",
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "bytes": stat.st_size,
        "all_hash": hashlib.sha256(normalize(" ".join(all_text)).encode()).hexdigest(),
        "sections": {key: " ".join(sections[key]) for key in TAILORED},
    }


def difference(left, right):
    union = left | right
    return round(100 * (1 - len(left & right) / len(union)), 2) if union else 0.0


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    paths = sorted(SOURCE.glob("*.docx"), key=lambda p: p.name.casefold())
    resumes = []
    errors = []
    for path in paths:
        try:
            resumes.append(read_resume(path))
        except Exception as exc:
            errors.append({"file": path.name, "error": str(exc)})
    if not resumes:
        raise SystemExit("No readable DOCX resumes found")
    section_sets = [{key: shingles(r["sections"][key]) for key in TAILORED} for r in resumes]
    tailored_sets = [set().union(*(section_sets[i][key] for key in TAILORED)) for i in range(len(resumes))]
    hash_groups = defaultdict(list)
    for r in resumes:
        hash_groups[r["all_hash"]].append(r["file"])
    metrics = [{"min": 101.0, "max": -1.0, "total": 0.0, "nearest": "", "exact_count": 0} for _ in resumes]
    pairs = []
    for i, j in combinations(range(len(resumes)), 2):
        left, right = resumes[i], resumes[j]
        diff = difference(tailored_sets[i], tailored_sets[j])
        exact = left["all_hash"] == right["all_hash"]
        pair = {
            "resume_a": left["file"],
            "resume_b": right["file"],
            "difference_pct": diff,
            "identical_text": "Yes" if exact else "No",
            "summary_pct": difference(section_sets[i]["Summary"], section_sets[j]["Summary"]),
            "strengths_pct": difference(section_sets[i]["Strengths"], section_sets[j]["Strengths"]),
            "results_pct": difference(section_sets[i]["Results"], section_sets[j]["Results"]),
            "experience_pct": difference(section_sets[i]["Experience"], section_sets[j]["Experience"]),
            "tools_pct": difference(section_sets[i]["Tools"], section_sets[j]["Tools"]),
        }
        pairs.append(pair)
        for a, b in ((i, j), (j, i)):
            metric = metrics[a]
            metric["total"] += diff
            metric["max"] = max(metric["max"], diff)
            if diff < metric["min"] or (diff == metric["min"] and resumes[b]["file"] < metric["nearest"]):
                metric["min"] = diff
                metric["nearest"] = resumes[b]["file"]
            metric["exact_count"] += exact
    pairs.sort(key=lambda p: (p["difference_pct"], p["resume_a"], p["resume_b"]))
    for r, metric in zip(resumes, metrics):
        r["nearest_difference_pct"] = metric["min"] if len(resumes) > 1 else None
        r["nearest_resume"] = metric["nearest"]
        r["average_difference_pct"] = round(metric["total"] / (len(resumes) - 1), 2) if len(resumes) > 1 else None
        r["exact_duplicate_peers"] = metric["exact_count"]
        r.pop("sections")
        r.pop("all_hash")
    exact_pairs = sum(p["identical_text"] == "Yes" for p in pairs)
    summary = {
        "source_folder": str(SOURCE),
        "resume_count": len(resumes),
        "unreadable": errors,
        "pair_count": len(pairs),
        "exact_text_duplicate_pairs": exact_pairs,
        "duplicate_groups": sum(len(group) > 1 for group in hash_groups.values()),
        "resumes_in_duplicate_groups": sum(len(group) for group in hash_groups.values() if len(group) > 1),
        "min_difference_pct": min(p["difference_pct"] for p in pairs) if pairs else None,
        "median_difference_pct": pairs[len(pairs) // 2]["difference_pct"] if pairs else None,
        "max_difference_pct": max(p["difference_pct"] for p in pairs) if pairs else None,
        "resume_dates": dict(Counter(r["modified"][:10] for r in resumes)),
    }
    (DEST / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with (DEST / "resumes.csv").open("w", newline="", encoding="utf-8-sig") as out:
        writer = csv.DictWriter(out, fieldnames=list(resumes[0]))
        writer.writeheader()
        writer.writerows(resumes)
    with (DEST / "pairs.csv").open("w", newline="", encoding="utf-8-sig") as out:
        writer = csv.DictWriter(out, fieldnames=list(pairs[0]))
        writer.writeheader()
        writer.writerows(pairs)
    indexes = {r["file"]: i + 1 for i, r in enumerate(resumes)}
    matrix = [[0.0] * len(resumes) for _ in resumes]
    for pair in pairs:
        i, j = indexes[pair["resume_a"]] - 1, indexes[pair["resume_b"]] - 1
        matrix[i][j] = matrix[j][i] = pair["difference_pct"]
    workbook_data = {
        "summary": summary,
        "index": [
            [indexes[r["file"]], r["company"], r["role"], r["job_id"], r["modified"],
             r["nearest_difference_pct"], indexes.get(r["nearest_resume"], ""),
             r["average_difference_pct"], r["exact_duplicate_peers"], r["file"]]
            for r in resumes
        ],
        "matrix": matrix,
        "closest": [
            [indexes[p["resume_a"]], indexes[p["resume_b"]], p["difference_pct"],
             p["identical_text"], p["summary_pct"], p["strengths_pct"], p["results_pct"],
             p["experience_pct"], p["tools_pct"]]
            for p in pairs[:250]
        ],
    }
    (DEST / "workbook-data.json").write_text(json.dumps(workbook_data, separators=(",", ":")), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print("Most similar nonidentical pairs:")
    for n, pair in enumerate((p for p in pairs if p["identical_text"] == "No"), start=1):
        print(pair["difference_pct"], pair["resume_a"], pair["resume_b"])
        if n >= 5:
            break


if __name__ == "__main__":
    main()
