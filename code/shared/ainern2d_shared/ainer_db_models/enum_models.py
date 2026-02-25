from __future__ import annotations

import enum


class RunStatus(str, enum.Enum):
	queued = "queued"
	running = "running"
	paused = "paused"
	degraded = "degraded"
	success = "success"
	failed = "failed"
	canceled = "canceled"


class RenderStage(str, enum.Enum):
	ingest = "ingest"
	entity = "entity"
	knowledge = "knowledge"
	plan = "plan"
	route = "route"
	execute = "execute"
	audio = "audio"
	video = "video"
	lipsync = "lipsync"
	compose = "compose"
	observe = "observe"


class JobStatus(str, enum.Enum):
	queued = "queued"
	enqueued = "enqueued"
	claimed = "claimed"
	running = "running"
	retrying = "retrying"
	success = "success"
	failed = "failed"
	canceled = "canceled"


class JobType(str, enum.Enum):
	extract_entities = "extract_entities"
	canonicalize_entities = "canonicalize_entities"
	match_assets = "match_assets"
	plan_storyboard = "plan_storyboard"
	plan_prompt = "plan_prompt"
	compile_dsl = "compile_dsl"
	synth_audio = "synth_audio"
	render_video = "render_video"
	render_lipsync = "render_lipsync"
	evaluate_quality = "evaluate_quality"
	compose_final = "compose_final"


class ArtifactType(str, enum.Enum):
	keyframe = "keyframe"
	prompt_bundle = "prompt_bundle"
	dsl_bundle = "dsl_bundle"
	shot_video = "shot_video"
	dialogue_wav = "dialogue_wav"
	mixed_audio = "mixed_audio"
	final_video = "final_video"
	subtitles = "subtitles"
	report = "report"


class EntityType(str, enum.Enum):
	person = "person"
	place = "place"
	org = "org"
	item = "item"
	skill = "skill"
	event = "event"
	clue = "clue"
	other = "other"


class AudioItemType(str, enum.Enum):
	dialogue = "dialogue"
	bgm = "bgm"
	sfx = "sfx"
	ambience = "ambience"


class MembershipRole(str, enum.Enum):
	owner = "owner"
	admin = "admin"
	editor = "editor"
	viewer = "viewer"
	service = "service"


class RagScope(str, enum.Enum):
	novel = "novel"
	chapter = "chapter"
	shot = "shot"
	feedback = "feedback"
	style_rule = "style_rule"


class RagSourceType(str, enum.Enum):
	chapter = "chapter"
	shot = "shot"
	feedback = "feedback"
	note = "note"
	rule = "rule"
	policy = "policy"
	persona = "persona"


class GateDecision(str, enum.Enum):
	pass_ = "pass"
	warn = "warn"
	fail = "fail"


class ProposalStatus(str, enum.Enum):
	draft = "draft"
	reviewing = "reviewing"
	approved = "approved"
	rejected = "rejected"
	rolled_back = "rolled_back"


class ExperimentStatus(str, enum.Enum):
	planned = "planned"
	running = "running"
	completed = "completed"
	stopped = "stopped"


class RolloutStatus(str, enum.Enum):
	planned = "planned"
	canary = "canary"
	full = "full"
	rolled_back = "rolled_back"
