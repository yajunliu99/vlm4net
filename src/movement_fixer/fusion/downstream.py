"""Interpret acquisition metadata without promoting nominal poses to lane truth."""


def camera_context(view):
    status=view.get("carriageway_status")
    if status=="nominal_outgoing_side":
        return {"side_label":"nominal outgoing side",
                "target_relation":"Camera metadata places it on the nominal target outgoing side. Check the visible lane markings and curb before accepting this correspondence; do not assume the target is across the center separation.",
                "camera_role":"outbound_primary_"+view["view_role"]}
    if status=="opposite_carriageway_auxiliary":
        return {"side_label":"opposite-side auxiliary",
                "target_relation":"Camera is on the opposing carriageway. Target outgoing pavement is across the center separation; do not count the camera's own lanes as receiving lanes.",
                "camera_role":"outbound_auxiliary_"+view["view_role"]}
    return {"side_label":"carriageway side unresolved",
            "target_relation":"Camera carriageway is unresolved. Establish the target pavement from heading, location, curb and center separation before associating any region.",
            "camera_role":"outbound_unresolved_"+view["view_role"]}


def acquisition_summary(manifest):
    views=manifest["views"]
    return {"mode":manifest["acquisition_mode"],"views":len(views),
            "new_panorama_queries_succeeded":sum(r.get("status")=="OK" for r in manifest.get("metadata_attempts",[])),
            "nominal_outgoing_views":sum(v.get("carriageway_status")=="nominal_outgoing_side" for v in views),
            "opposing_auxiliary_views":sum(v.get("carriageway_status")=="opposite_carriageway_auxiliary" for v in views),
            "unique_panoramas":len({v["pano_id"] for v in views}),
            "note":"Carriageway side follows nominal metadata geometry, not surveyed lane localization. Capture dates and original panorama groups must be retained."}
