from types import SimpleNamespace

import pytest

from app.capability.generic import (
    I2V, GenerateError, GenerateIn, ModelInfo, RefIn, build_payload,
    catalog_models, fit_refs, validate_video_controls,
)


def model():
    return ModelInfo(endpoint_id="local", endpoint_name="local", model="ltx-2.5-22b-distilled",
                     label="LTX-2.5", capability=I2V, fps=[4, 8, 12, 24, 25],
                     control_types=["layout", "depth", "pose", "canny", "union"])


@pytest.mark.parametrize("fps", [4, 8, 12])
def test_manual_low_fps_is_sent_to_inference_without_replacement(fps):
    body = GenerateIn(media="video", model=model().model, prompt="He raises his hand.", video_fps=fps)
    validate_video_controls(body, model())
    assert build_payload(I2V, body, 768, 448, 5000, 1)["fps"] == fps


def test_low_fps_rejected_for_model_only_advertising_24():
    other = model()
    other.fps = [24]
    with pytest.raises(GenerateError, match="不支持 4") as error:
        validate_video_controls(GenerateIn(media="video", video_fps=4), other)
    assert error.value.code == "UNSUPPORTED_VIDEO_FPS"


def test_layout_control_survives_reference_fitting_and_payload():
    driver = RefIn(node_id="white_model", kind="video", role="control_video", tag="layout",
                   url="http://localhost:8100/media/layout.mp4")
    body = GenerateIn(media="video", video_fps=8, refs=[driver])
    validate_video_controls(body, model())
    fitted, _ = fit_refs(I2V, body.refs, model())
    payload = build_payload(I2V, body.model_copy(update={"refs": fitted}), 768, 448, 5000, 1)
    assert payload["control"] == {"type": "layout", "video": {"url": driver.url}}


def test_unsupported_layout_is_rejected_before_reference_can_be_dropped():
    other = model()
    other.control_types = ["v2v"]
    body = GenerateIn(media="video", refs=[RefIn(kind="video", role="control_video", tag="layout")])
    with pytest.raises(GenerateError) as error:
        validate_video_controls(body, other)
    assert error.value.code == "UNSUPPORTED_VIDEO_CONTROL"


def test_catalog_reads_native_fps_and_layout_from_gateway_discovery():
    endpoint = SimpleNamespace(id="local", name="local", base_url="http://127.0.0.1:7999", caps_cache_json={
        "capabilities": [{"capability": I2V, "models": [{"id": "ltx", "limits": {"fps": [4, 8, 12, 24, 25]},
                                                        "control_types": ["layout"]}]}]})
    entry = catalog_models(endpoint, [I2V])[0]
    assert entry.fps == [4, 8, 12, 24, 25]
    assert entry.control_types == ["layout"]
