"""Canonical view names and legacy adapters, shared with real consumers."""
ALIASES = {"expr_sorrow": "expr_sad", "expr_happy": "expr_laugh"}
VIEW_KEYS = (
    "body_front", "body_back", "body_side",
    "face_front", "face_left", "face_right", "face_back",
    "expr_joy", "expr_anger", "expr_sad", "expr_laugh", "expr_surprise",
    "expr_fear", "expr_think", "expr_disgust", "expr_doubt",
)
LEGACY_VIEWS = {
    "front": ("body_front", "legacy_mapped", "unspecified"),
    "back": ("body_back", "legacy_mapped", "back"),
    "profile_left": ("body_side", "legacy_approximate", "left"),
    "bust": ("face_front", "legacy_approximate", "front"),
}


def canonical_views(ref: dict) -> dict[str, dict]:
    """Read legacy panels first; explicit canonical bindings take precedence."""
    out: dict[str, dict] = {}
    legacy = ref.get("views") or {}
    if isinstance(legacy, dict):
        for old, (key, status, side) in LEGACY_VIEWS.items():
            item = legacy.get(old)
            if isinstance(item, dict) and item.get("asset_id"):
                out[key] = {**item, "legacy_key": old, "status": status, "side": side}
    panels = ref.get("sheet_panels") or []
    if isinstance(panels, list):
        for item in panels:
            if not isinstance(item, dict):
                continue
            key = ALIASES.get(item.get("key"), item.get("key"))
            if key in VIEW_KEYS and item.get("asset_id"):
                out[key] = {**item, "legacy_key": item.get("key"), "status": "bound_unreviewed"}
    stored = ref.get("canonical_views") or {}
    if isinstance(stored, dict):
        for key, item in stored.items():
            key = ALIASES.get(key, key)
            if key in VIEW_KEYS and isinstance(item, dict) and item.get("asset_id"):
                out[key] = dict(item)
    return out


def preferred_canonical_view(facing: str | None, shot_size: str | None) -> str | None:
    if facing == "three_quarter":
        return None  # The standard pack has no 3/4 slot; retain the actual extended view.
    close = str(shot_size or "").lower() in {"ecu", "cu", "mcu", "close", "closeup"}
    if close:
        return {"profile_left": "face_left", "profile_right": "face_right",
                "away": "face_back"}.get(facing, "face_front")
    return {"away": "body_back", "profile_left": "body_side",
            "profile_right": "body_side"}.get(facing, "body_front")
