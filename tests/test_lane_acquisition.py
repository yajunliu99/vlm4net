import copy
import csv
import io
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from movement_fixer.fusion.control_acquisition import StreetViewClient
from movement_fixer.fusion.coordinates import local_lonlat
from movement_fixer.fusion.lane_acquisition import MapboxClient, acquire, mapbox_viewport, plan_site, site_files
from movement_fixer.hybrid.sampling import audit_sampling

CENTER = (-111.94, 33.42)


def line(*points):
    return "LINESTRING (" + ", ".join(f"{lon:.8f} {lat:.8f}" for lon, lat in (local_lonlat(e, n, CENTER) for e, n in points)) + ")"


def write_tee(folder):
    """A two-way east-west road with a two-way stem to the south; every link has its own carriageway direction."""
    nodes = [{"node_id": 1, "x_coord": CENTER[0], "y_coord": CENTER[1]}]
    for i, (e, n) in enumerate([(-300, 0), (300, 0), (0, -300)], start=2):
        lon, lat = local_lonlat(e, n, CENTER)
        nodes.append({"node_id": i, "x_coord": lon, "y_coord": lat})
    rows = []
    for k, (other, far) in enumerate([(2, (-300, 0)), (3, (300, 0)), (4, (0, -300))]):
        rows.append({"link_id": 10 + 2 * k, "from_node_id": other, "to_node_id": 1, "geometry": line(far, (0, 0)), "lanes": 2,
                     "allowed_uses": "auto", "from_biway": 1, "name": "Stem Rd" if other == 4 else "Main St"})
        rows.append({"link_id": 11 + 2 * k, "from_node_id": 1, "to_node_id": other, "geometry": line((0, 0), far), "lanes": 2,
                     "allowed_uses": "auto", "from_biway": 1, "name": "Stem Rd" if other == 4 else "Main St"})
    for name, data in (("node.csv", nodes), ("link.csv", rows)):
        with open(folder / name, "w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(data[0]))
            writer.writeheader()
            writer.writerows(data)
    return folder / "node.csv", folder / "link.csv"


class Response:
    status_code = 200

    def __init__(self, body=None, size=(8, 8)):
        self.body = body
        buffer = io.BytesIO()
        Image.new("RGB", size, "gray").save(buffer, format="JPEG")
        self.content = buffer.getvalue()

    def json(self):
        return self.body


class StreetView:
    """Snaps every request to a panorama 1 m away; `empty` positions have no coverage."""

    def __init__(self, empty=()):
        self.calls, self.empty = [], empty

    def get(self, url, params, timeout):
        self.calls.append(url)
        if url.endswith("metadata"):
            lat, lon = map(float, params["location"].split(","))
            if any(abs(lat - a) < 1e-6 and abs(lon - b) < 1e-6 for a, b in self.empty):
                return Response({"status": "ZERO_RESULTS"})
            return Response({"status": "OK", "location": {"lng": lon + 1e-5, "lat": lat}, "pano_id": f"p{lat:.6f}_{lon:.6f}", "date": "2025-11"})
        return Response()


class Mapbox:
    def __init__(self):
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append((url, params))
        return Response(size=(2560, 2560))


def clients(cache, street, mapbox, cache_only=False):
    s = StreetViewClient(ROOT, cache / "gsv", {"image_size": [640, 640], "max_metadata_requests": 80, "max_image_requests": 64},
                         cache_only=cache_only, session=street)
    s.key = "test-only"
    m = MapboxClient(ROOT, cache / "sat", cache_only=cache_only, session=mapbox)
    m.token = "pk.test-token-never-recorded"
    return s, m


class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.node_csv, self.link_csv = write_tee(self.folder)

    def tearDown(self):
        self.tmp.cleanup()

    def test_viewport_follows_the_tile_arithmetic(self):
        view = mapbox_viewport(CENTER, 19, (1280, 1280))
        self.assertAlmostEqual(view.ground_mpp(CENTER[1]), 0.0623, places=4)
        x, y = view.to_pixel(*CENTER)
        self.assertAlmostEqual(x, 1280, places=6)
        self.assertAlmostEqual(y, 1280, places=6)

    def test_plan_names_legs_and_arms_from_the_network(self):
        plan = plan_site(self.node_csv, self.link_csv, 1)
        legs = {l["section_id"]: l["arm"] for l in plan["legs"]}
        self.assertEqual(legs, {"in_EB": "W", "out_WB": "W", "in_WB": "E", "out_EB": "E", "in_NB": "S", "out_SB": "S"})
        self.assertEqual(plan["name"], "Main St x Stem Rd")
        self.assertEqual(plan["budget"]["street_view_images"]["upper_bound"], 3 * 4 + 3 * 3 * 2)

    def test_tee_acquisition_feeds_classification_and_exit_audit(self):
        plan = plan_site(self.node_csv, self.link_csv, 1)
        street, mapbox = StreetView(), Mapbox()
        result = acquire(plan, *clients(self.folder, street, mapbox))
        self.assertEqual((len(result["views"]), result["missing"], result["stopped"]), (30, [], None))
        self.assertEqual(sum(u.endswith("metadata") for u in street.calls), 18)
        site, base, manifest = site_files(plan, result, ROOT)
        self.assertEqual(site["satellite"]["georeference"]["kind"], "viewport")
        self.assertEqual(len(base["context_views"]), 9)
        self.assertEqual(sorted(s["direction"] for s in base["sources"].values() if s.get("reverse_view")), ["EB", "NB", "WB"])
        self.assertEqual({v["target_section"] for v in manifest["views"]}, {"out_EB", "out_WB", "out_SB"})
        self.assertTrue(all(v["carriageway_status"] == "nominal_outgoing_side" for v in manifest["views"]))
        # Forward views face travel toward the junction; look-back views the other way.
        nb = {s["camera_role"]: s["compass_heading_deg"] for s in base["sources"].values() if s.get("direction") == "NB" and s.get("sampling_position") == "near"}
        self.assertAlmostEqual(nb["forward_primary"], 0, delta=1)
        self.assertAlmostEqual(nb["reverse_auxiliary"], 180, delta=1)
        config = {**base, "sections": [{"id": l["section_id"], "kind": l["kind"], "direction": l["direction"], "heading_deg": l["heading_deg"]}
                                       for l in plan["legs"]]}
        self.assertTrue(audit_sampling(config)["complete"])
        record = json.dumps([site, base, manifest]) + "".join(p.read_text() for p in (self.folder / "sat").glob("*.json"))
        self.assertNotIn("pk.test-token-never-recorded", record)
        self.assertNotIn("test-only", record)

    def test_band_without_coverage_is_missing_not_filled(self):
        plan = plan_site(self.node_csv, self.link_csv, 1)
        stem = next(l for l in plan["legs"] if l["section_id"] == "in_NB")
        empty = [tuple(reversed(r["requested_lonlat"])) for r in stem["requests"]["far"]]
        street = StreetView(empty=empty)
        result = acquire(plan, *clients(self.folder, street, Mapbox()))
        self.assertEqual(result["missing"], [{"section_id": "in_NB", "direction": "NB", "position": "far", "reason": "no_acceptable_panorama"}])
        self.assertEqual(sum(u.endswith("metadata") for u in street.calls), 18 + 2)  # both fallbacks were tried
        site, base, manifest = site_files(plan, result, ROOT)
        config = {**base, "sections": [{"id": l["section_id"], "kind": l["kind"], "direction": l["direction"], "heading_deg": l["heading_deg"]}
                                       for l in plan["legs"]]}
        audit = audit_sampling(config)
        self.assertEqual((audit["complete"], audit["missing"]), (False, [("NB", "far")]))

    def test_far_camera_follows_the_road_past_a_short_link(self):
        rows = list(csv.DictReader(open(self.link_csv)))
        nodes = list(csv.DictReader(open(self.node_csv)))
        lon, lat = local_lonlat(-60, 0, CENTER)
        nodes.append({"node_id": 9, "x_coord": lon, "y_coord": lat})
        for r in rows:  # the west arm now ends at a node 60 m out; the road continues on new links
            if r["link_id"] == "10":
                r.update(from_node_id=9, geometry=line((-60, 0), (0, 0)))
            if r["link_id"] == "11":
                r.update(to_node_id=9, geometry=line((0, 0), (-60, 0)))
        rows += [{**rows[0], "link_id": 20, "from_node_id": 2, "to_node_id": 9, "geometry": line((-300, 3), (-60, 0))},
                 {**rows[0], "link_id": 21, "from_node_id": 9, "to_node_id": 2, "geometry": line((-60, 0), (-300, 3))},
                 {**rows[0], "link_id": 22, "from_node_id": 9, "to_node_id": 8, "geometry": line((-60, 0), (-60, -200)), "name": "Side St"}]
        for path, data in ((self.node_csv, nodes), (self.link_csv, rows)):
            with open(path, "w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(data[0]))
                writer.writeheader()
                writer.writerows(data)
        plan = plan_site(self.node_csv, self.link_csv, 1)
        west = next(l for l in plan["legs"] if l["section_id"] == "in_EB")
        self.assertGreater(west["line"][-1][0] * -1, 250)  # continued straight onto link 20, not the side street
        result = acquire(plan, *clients(self.folder, StreetView(), Mapbox()))
        self.assertEqual(result["missing"], [])

    def test_replay_from_cache_makes_no_request(self):
        plan = plan_site(self.node_csv, self.link_csv, 1)
        first = acquire(plan, *clients(self.folder, StreetView(), Mapbox()))
        street, mapbox = StreetView(), Mapbox()
        again = acquire(plan, *clients(self.folder, street, mapbox, cache_only=True))
        self.assertEqual((street.calls, mapbox.calls), ([], []))
        self.assertEqual([v["image_sha256"] for v in again["views"]], [v["image_sha256"] for v in first["views"]])


if __name__ == "__main__":
    unittest.main()
