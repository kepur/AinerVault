from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v2.canvas_gen import SceneBriefIn, scene_brief


def test_visual_brief_uses_source_blocks_and_localized_actor_names(monkeypatch):
    from app.api.v2 import script as script_api
    from app.pipelines import base
    script={'id':'doc','scenes':[{'id':'scene','location_text':'走廊','blocks':[
        {'id':'action','text':'两名少年围堵学生。'},
        {'id':'line','text':'Give it!','speaker_entity_id':'a','speaker':'Tyler Stone'}]}]}
    monkeypatch.setattr(script_api,'get_script',lambda *args:script)
    seen=[]
    def chat(*args,**kwargs):
        seen.append((args[1],kwargs))
        return {'action_en':'Tyler and another boy corner a student.','framing_en':'Three people in the corridor.','people_count':3,'blocking':[{'entity_id':eid,'placement_en':'a distinct location','appearance_en':'a teenage boy','screen_x':.13+n*.24} for n,eid in enumerate(['a','b','c'])]},SimpleNamespace(id='task')
    monkeypatch.setattr(base,'chat_json',chat)
    class DB:
        def get(self,model,eid):
            if model.__name__=='Chapter':return SimpleNamespace(novel_id='book',id='chapter')
            return SimpleNamespace(novel_id='book',kind=SimpleNamespace(value='character'),display_name=eid)
        def commit(self):pass
    body=SceneBriefIn(chapter_id='chapter',script_doc_id='doc',scene_id='scene',block_ids=['action'],character_ids=['a','b','c'])
    out=scene_brief(body,DB())
    assert out['source_text']==['两名少年围堵学生。'] and out['core_task_id']=='task'
    assert 'Tyler Stone' in seen[0][0][1]['content'] and seen[0][1]['purpose']=='shot_plan'
    with pytest.raises(HTTPException) as err:scene_brief(body.model_copy(update={'block_ids':['other-scene-block']}),DB())
    assert err.value.status_code==422 and len(seen)==1
    with pytest.raises(HTTPException) as err:scene_brief(body.model_copy(update={'script_doc_id':'old-doc'}),DB())
    assert err.value.status_code==409 and len(seen)==1


def test_visual_brief_rejects_wrong_count_or_untranslated_action(monkeypatch):
    from app.api.v2 import script as script_api
    from app.pipelines import base
    monkeypatch.setattr(script_api,'get_script',lambda *args:{'id':'doc','scenes':[{'id':'scene','blocks':[{'id':'action','text':'中文动作'}]}]})
    class DB:
        def get(self,model,eid):return SimpleNamespace(novel_id='book',id=eid,kind=SimpleNamespace(value='character'),display_name=eid)
        def commit(self):pass
    body=SceneBriefIn(chapter_id='chapter',script_doc_id='doc',scene_id='scene',block_ids=['action'],character_ids=['a'])
    for action,count in [('英文仍未生成',1),('A student waits.',2)]:
        monkeypatch.setattr(base,'chat_json',lambda *args,a=action,n=count,**kwargs:({'action_en':a,'framing_en':'A student.','people_count':n},SimpleNamespace(id='t')))
        with pytest.raises(HTTPException) as err:scene_brief(body,DB())
        assert err.value.status_code==502


def test_added_actor_requires_explicit_adaptation():
    from app.api.v2.canvas_gen import DirectorActor
    actor=DirectorActor(entity_id='da_'+'a'*24,name='Kyle Reed',design='Blond boy in navy tracksuit')
    body=SceneBriefIn(chapter_id='chapter',script_doc_id='doc',scene_id='scene',block_ids=['action'],character_ids=[actor.entity_id],added_actors=[actor])
    from app.api.v2 import script as script_api
    from unittest.mock import patch
    class DB:
        def get(self,*args):return SimpleNamespace(novel_id='book')
    with patch.object(script_api,'get_script',return_value={'id':'doc','scenes':[{'id':'scene','blocks':[{'id':'action','text':'original action'}]}]}):
        with pytest.raises(HTTPException) as err:scene_brief(body,DB())
        assert err.value.status_code==422
