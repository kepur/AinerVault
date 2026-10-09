"""Typed canvas references to shared stages, never disguised as image URLs."""
from app.production import service as sources, stages
from app.production.schema import ResourceRef


def resolve(db, board, ref: ResourceRef):
    if any(ref.binding.model_dump().values()):
        raise sources.ProductionError("stage_binding_invalid", "舞台/镜头引用不接受角色视图或实例覆盖")
    stage_id, _, coverage_id = ref.id.partition(":") if ref.kind == "coverage" else (ref.id, "", "")
    if ref.kind == "coverage" and not coverage_id:
        raise sources.ProductionError("coverage_id_invalid", "镜头引用 ID 必须为 stage_id:coverage_id")
    _, scene = stages.get(db, stage_id, board.id)
    content = stages.content_of(scene)
    stages.validate(content)
    stages.assert_consumable(content)
    stages.projection(db, scene)
    # Re-resolve every atomic source, so a changed character pack blocks an old
    # stage even when its own saved geometry has not changed.
    resources = stages.bind_sources(db, board, content)
    stage = stages.out(scene, False)
    coverage = stages.coverage_of(content, coverage_id).model_dump() if coverage_id else None
    return {"id": ref.id, "kind": ref.kind, "name": coverage["title"] if coverage else scene.title,
            "revision": sources.revision({"stage_id": scene.id, "content": content.model_dump(mode="json"), "coverage": coverage}),
            "stage_id": scene.id, "stage_version": scene.version, "stage_revision": stage["revision"],
            "box_project_id": scene.box_project_id, "coverage": coverage,
            "coverages": [c.model_dump() for c in content.coverages],
            "dependencies": [{"instance_id": key, "ref": value.model_dump(mode="json"),
                              "resource_revision": resources[key]["revision"]}
                             for key, value in content.bindings.items()],
            "consumption": {"preview": "shared_runtime", "generation": "not_submitted",
                            "contact_ik_collision": "not_implemented", "semantic_events": "state_only"}}


def consume(db, board_id, ref, *, bake=False):
    if ref.kind not in {"stage", "coverage"} or not ref.revision:
        raise sources.ProductionError("stage_reference_required", "请选择明确版本的舞台或镜头引用")
    board = sources.board(db, board_id)
    stage_id = ref.id.partition(":")[0] if ref.kind == "coverage" else ref.id
    _, scene = stages.get(db, stage_id, board_id, lock=True)
    context, _ = sources.context_for(db, board)
    item = sources.resolve_one(db, board, context, ref)
    content, doc, resources = stages.resolve_doc(db, scene, board, scene.version)
    result = {"ref": item["ref"], "resource": item["resource"], "doc": doc}
    if bake:
        if ref.kind != "coverage":
            raise sources.ProductionError("coverage_reference_required", "请选镜头节点，舞台没有唯一成片机位与时间窗")
        coverage_id = ref.id.partition(":")[2]
        result.update(stages.bake_coverage(db, scene, board, scene.version, coverage_id))
        result["sources"] = resources
        result["state_plan"] = {"initial_state": content.initial_state,
                                "events": [e.model_dump() for e in content.events]}
        result["control_revision"] = sources.revision({"ref": item["ref"], "sources":
            {k: r["revision"] for k, r in resources.items()}, "coverage": result["coverage"]})
    return result
