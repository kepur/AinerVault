"""生成 Unreal Python：把序列排进 Movie Render Queue 并开渲（PIE 执行器）。"""
from __future__ import annotations

import json
from typing import Any

TEMPLATE = '''# Ainer Director · 排渲染队列（由 ainer-core 生成，勿手改）
import json
import unreal

R = json.loads({render!r})
subsystem = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
queue = subsystem.get_queue()
job = queue.allocate_new_job(unreal.MoviePipelineExecutorJob)
job.sequence = unreal.SoftObjectPath(R["sequence"])
job.map = unreal.SoftObjectPath(R["level"])
job.job_name = R["name"]
if R.get("preset"):
    job.set_configuration(unreal.EditorAssetLibrary.load_asset(R["preset"]))
cfg = job.get_configuration()
out = cfg.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
out.output_resolution = unreal.IntPoint(R["resolution"][0], R["resolution"][1])
if R.get("output_dir"):
    out.output_directory = unreal.DirectoryPath(R["output_dir"])
out.file_name_format = "{{sequence_name}}.{{frame_number}}"
cfg.find_or_add_setting_by_class(unreal.MoviePipelineDeferredPassBase)
cfg.find_or_add_setting_by_class(unreal.MoviePipelineImageSequenceOutput_PNG)
subsystem.render_queue_with_executor(unreal.MoviePipelinePIEExecutor)
unreal.log("Ainer：已排队渲染 %s" % R["name"])
'''


def generate(render_plan: dict[str, Any]) -> str:
    return TEMPLATE.format(render=json.dumps(render_plan, ensure_ascii=False))
