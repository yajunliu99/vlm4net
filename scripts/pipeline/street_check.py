"""Send approaches whose street-view lane count differs from their traced lanes back to the tracing review loop.

Reads a finished classification run (lanes.json, lane_use_audits.json with street_view_counts) and the tracing
run it was built on. For each mismatch (autoloop/street_check.py) the section's review loop resumes from its final
strips with the mismatch as an issue, the street view shown with the boundaries projected onto it. Revised sections
replace the old ones in the tracing run (the old strips are kept in its history); geometry/street_check.json records
the outcome and whether classification has to run again. Runs once per tracing run.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from movement_fixer.autoloop import street_panel
from movement_fixer.autoloop.geometry_stage import load_georeference, plan_site, run_section
from movement_fixer.autoloop.street_check import issue, mismatches
from movement_fixer.autoloop.strips import Frame
from movement_fixer.hybrid.common import read_json, write_json
from movement_fixer.hybrid.inference import StageClient


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--site", type=Path, required=True, help="tracing site config (site.json)")
    p.add_argument("--geometry", type=Path, required=True, help="tracing run")
    p.add_argument("--evidence", type=Path, required=True, help="classification run built on it")
    p.add_argument("--max-rounds", type=int, default=2)
    p.add_argument("--max-api-calls", type=int, default=16)
    p.add_argument("--cache-only", action="store_true")
    p.add_argument("--reuse-cache-from", type=Path, action="append", default=[])
    a = p.parse_args()
    geometry, evidence = a.geometry.resolve(), a.evidence.resolve()
    g = geometry / "geometry"
    config = read_json(a.site)
    image, _, policy, _ = plan_site(config, ROOT)
    policy = {**policy, "max_rounds": a.max_rounds}
    to_pixel, _ = load_georeference(config["satellite"]["georeference"], ROOT)
    base = a.site.with_name("base_config.json")
    street_views = read_json(base) if base.exists() else None
    found = mismatches(read_json(evidence / "lanes.json"), read_json(evidence / "lane_use_audits.json"), read_json(evidence / "inference_config.json"))
    history = read_json(g / "history.json")
    sections = read_json(g / "sections.json")
    plan = {s["id"]: s for s in read_json(g / "plan.json")["sections"]}
    by_history = {h["section_id"]: i for i, h in enumerate(history)}
    by_section = {s["id"]: i for i, s in enumerate(sections)}
    client = StageClient(ROOT, geometry, {**config.get("models", {}).get("review", config.get("models", {}).get("draft", {})),
                                          "max_api_calls": a.max_api_calls}, a.cache_only, [x.resolve() for x in a.reuse_cache_from])
    results, changed = [], False
    for m in found:
        sid = m["section_id"]
        record = history[by_history[sid]] if sid in by_history else None
        if not record or not record.get("final") or sid not in by_section:
            results.append({**m, "outcome": "no traced strips to review"})
            continue
        spec = {**plan[sid], "frame": Frame(tuple(record["frame"]["center"]), record["frame"]["heading_deg"], record["frame"]["width"],
                                            record["frame"]["height"]), "stations": record["stations"]}
        view = street_panel.pick_view(street_views, m["direction"]) if street_views else None
        street = {"view": view, "image": street_panel.load(view, ROOT), "to_pixel": to_pixel} if view else None
        section, rerun = run_section(image, spec, client, client, g, policy, lambda: client.calls < a.max_api_calls, street,
                                     start=record["final"], extra_issues=[issue(m)])
        outcome = {**m, "outcome": rerun["status"], "stop_reason": rerun["stop_reason"], "revised": rerun["revised"],
                   "rounds": rerun["rounds"], "regions_before": len(record["final"]["edges"]) - 1, "regions_after": len(rerun["final"]["edges"]) - 1}
        results.append(outcome)
        if rerun["revised"]:
            changed = True
            old = sections[by_section[sid]]
            section.update({k: old[k] for k in ("window_anchor", "street_view", "contrast_stretched", "shade_panel") if k in old})
            sections[by_section[sid]] = section
            history[by_history[sid]] = {**record, "final": rerun["final"], "status": rerun["status"], "street_check": {
                "issue": issue(m), "rounds": rerun["rounds"], "strips_before": record["final"]}}
    if changed:
        write_json(g / "sections.json", sections)
        write_json(g / "history.json", history)
    summary = {"flagged": len(found), "revised": sum(bool(r.get("revised")) for r in results), "classification_outdated": changed,
               "vlm_calls_this_run": client.calls, "vlm_cache_hits_this_run": client.hits, "results": results,
               "scope": "Street-view counts are model readings; a mismatch prompts a review, it never overwrites the geometry."}
    write_json(g / "street_check.json", summary)
    print(json.dumps({k: summary[k] for k in ("flagged", "revised", "classification_outdated", "vlm_calls_this_run")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
