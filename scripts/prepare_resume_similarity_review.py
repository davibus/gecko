"""Build a readable review list from the Gecko Main similarity audit."""

from pathlib import Path
import csv
import json


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "reports" / "resume-similarity"


def read_csv(name):
    with (AUDIT / name).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main():
    resumes = {row["file"]: row for row in read_csv("resumes.csv")}
    parent = {name: name for name in resumes}

    def find(name):
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    def union(left, right):
        parent[find(left)] = find(right)

    pairs = read_csv("pairs.csv")
    for pair in pairs:
        if pair["identical_text"] == "Yes":
            union(pair["resume_a"], pair["resume_b"])
    components = {}
    for name in resumes:
        components.setdefault(find(name), []).append(name)
    duplicate_groups = []
    for names in components.values():
        if len(names) < 2:
            continue
        rows = [resumes[name] for name in names]
        job_ids = sorted({row["job_id"] for row in rows})
        roles = sorted({row["role"] for row in rows})
        duplicate_groups.append({
            "company": rows[0]["company"],
            "resume_count": len(names),
            "job_id_count": len(job_ids),
            "role_count": len(roles),
            "priority": "Different job IDs" if len(job_ids) > 1 else "Same job ID / versions",
            "roles": "; ".join(roles),
            "job_ids": "; ".join(job_ids),
            "files": "; ".join(sorted(names)),
        })
    duplicate_groups.sort(key=lambda row: (row["job_id_count"] <= 1, -row["job_id_count"], -row["resume_count"], row["company"]))
    review = []
    for pair in pairs:
        difference = float(pair["difference_pct"])
        if difference >= 10:
            continue
        left = resumes[pair["resume_a"]]
        right = resumes[pair["resume_b"]]
        same_job = left["job_id"] == right["job_id"]
        identical = pair["identical_text"] == "Yes"
        if identical and not same_job:
            priority, category = 1, "Same text, different job ID"
        elif not identical and not same_job:
            priority, category = 2, "Very close, different job ID"
        elif identical:
            priority, category = 3, "Same text, same job ID"
        else:
            priority, category = 4, "Very close, same job ID"
        review.append({
            "priority": priority,
            "category": category,
            "difference": difference,
            "company_a": left["company"],
            "role_a": left["role"],
            "job_id_a": left["job_id"],
            "company_b": right["company"],
            "role_b": right["role"],
            "job_id_b": right["job_id"],
            "file_a": left["file"],
            "file_b": right["file"],
            "summary_difference": float(pair["summary_pct"]),
            "experience_difference": float(pair["experience_pct"]),
        })
    review.sort(key=lambda row: (row["priority"], row["difference"], row["company_a"], row["role_a"], row["role_b"]))
    counts = {
        "different_job_exact_pairs": sum(row["priority"] == 1 for row in review),
        "different_job_close_pairs": sum(row["priority"] == 2 for row in review),
        "same_job_exact_pairs": sum(row["priority"] == 3 for row in review),
        "same_job_close_pairs": sum(row["priority"] == 4 for row in review),
        "total_under_10_pct_pairs": len(review),
    }
    payload = {"counts": counts, "duplicate_groups": duplicate_groups, "review": review}
    (AUDIT / "review-plan.json").write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
