from app.capability.generic import GenerateIn, ModelInfo, canvas_size
from app.pipelines.char_sheet import panel_prompt


def model(name='ltx-2.5-22b-distilled'):
    return ModelInfo('local','Local',name,'LTX','video.image_to_video',sizes=[(576,320),(832,448),(1024,576)],size_multiple=64)


def test_old_catalog_cannot_round_fast_ltx_to_832():
    body=GenerateIn(media='video',resolution='480p')
    assert canvas_size(body,model())[:2]==(768,448)
    assert canvas_size(body.model_copy(update={'aspect_ratio':'9:16'}),model())[:2]==(448,768)
    assert canvas_size(body.model_copy(update={'resolution':'720p'}),model())[:2]==(1024,576)
    assert canvas_size(body,model('another-model'))[:2]==(832,448)


def test_existing_canvas_nodes_use_the_same_fast_profile():
    from app.pipelines.canvas_exec import _image_size
    assert _image_size({'resolution':'480p','aspect_ratio':'16:9'},model(),(768,448)) == (768,448)
    assert _image_size({'resolution':'480p','aspect_ratio':'9:16'},model(),(768,448)) == (448,768)
    assert _image_size({'resolution':'720p'},model(),(768,448)) == (1024,576)


def test_same_card_graph_can_produce_anime_without_changing_video_prompts():
    old=panel_prompt('body_back')
    anime=panel_prompt('body_back',style='anime')
    assert 'photorealistic photo' in old
    assert 'photorealistic photo' not in anime and 'same person' in anime and 'back to the camera' in anime


def test_ltx_draft_keeps_both_stages_with_two_refinement_steps():
    from app.capability.generic import I2V,build_payload
    body=GenerateIn(media='video',model='ltx-2.5-22b-distilled',ltx_stage2_steps=2,seed=1)
    payload=build_payload(I2V,body,768,448,5000,1)
    assert payload['params']=={'seed':1,'stage2_steps':2}
    assert 'quality' not in payload  # Not a stage-one-only preview.
    assert build_payload(I2V,body.model_copy(update={'ltx_stage2_steps':None}),768,448,5000,1)['params']=={'seed':1}


def test_twelve_fps_and_real_motion_reach_small_ltx_payload():
    from app.capability.generic import I2V,build_payload
    body=GenerateIn(media='video',model='ltxv-2b-distilled',video_fps=12,video_motion='animate')
    payload=build_payload(I2V,body,800,480,5500,1)
    assert payload['fps']==12 and payload['motion']=='animate'
    assert build_payload(I2V,GenerateIn(media='video'),768,448,5000,1)['fps']==24
