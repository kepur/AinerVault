#!/usr/bin/env python3
"""D4 independent design/structure audit. Never imports product/model code."""
import argparse
import copy
import hashlib
import json
import re
import sys
from fractions import Fraction
from importlib.metadata import version
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path('/Users/mac/AinerWorkFlow/AinerHub_IDEA')
OUT = ROOT / 'reports/production-brain/D1-independent-r2'
SCHEMA = ROOT / 'docs/v2/production_brain/performance_interface_v0.schema.json'
DOC = ROOT / 'docs/v2/production_brain/performance_interface_v0.md'
R1 = ROOT / 'reports/production-brain/D1-r2'
RELAY = Path('/Users/mac/AinerWorkFlow/AinerRelay')
ERRORS = [
    'unknown_actor', 'stale_revision', 'invalid_time_curve', 'unknown_controller',
    'out_of_range', 'missing_audio_alignment', 'lock_conflict', 'control_conflict',
    'unsupported_action', 'changed_past',
]


def sha(path):
    data = path.read_bytes()
    return {'path': str(path), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--failure-control', action='store_true')
    args = parser.parse_args()
    s = json.loads(SCHEMA.read_text())
    Draft202012Validator.check_schema(s)
    validator = Draft202012Validator(s)
    rows, probes, cases = [], [], []

    def check(name, data, expected):
        errors = sorted(validator.iter_errors(data), key=lambda e: str(list(e.path)))
        valid = not errors
        rows.append({'case': name, 'expected_valid': expected, 'actual_valid': valid,
                     'pass': valid == expected,
                     'errors': [{'path': '/' + '/'.join(map(str, e.path)), 'message': e.message,
                                 'schema_path': list(e.schema_path)} for e in errors]})
        cases.append({'case': name, 'expected_valid': expected, 'instance': data})

    def semantic_probe(name, data, future_rejection, paired_request=None):
        valid = validator.is_valid(data)
        probes.append({'case': name, 'schema_accepts': valid,
                       'future_semantic_requirement': future_rejection,
                       'interpretation': 'Documented semantic-layer boundary; no semantic implementation tested.',
                       'instance': data, 'paired_request': paired_request})

    binding = {'plan_id': 'd4-independent-plan', 'plan_revision': 7,
               'beat_id': 'beat-reveal', 'event_id': 'event-transform',
               'world_id': 'world-fixture', 'world_version': 11,
               'scene_id': 'scene-fixture', 'scene_revision': 3,
               'take_id': 'take-d4', 'actor_id': 'actor-1',
               'character_ref': 'pending:D5/d4-character', 'sim_hz': 120, 'render_fps': 24}
    audio = {'asset_ref': 'fixture:independent/no-real-audio', 'sha256': 'b' * 64,
             'sample_rate': 44100, 'anchor_tick': 120, 'offset_samples': -2205,
             'alignment': {'status': 'aligned', 'ref': 'fixture:independent/no-real-alignment',
                           'sha256': 'c' * 64}}
    request = {'protocol': 'hub.performance/v0', 'record_kind': 'request',
               'request_id': 'request-d4-independent', 'binding': binding,
               'intent': 'hesitant', 'intensity': 0.45, 'target_ref': 'object-reveal',
               'start_tick': 120, 'duration_ticks': 480, 'locks': [], 'audio_ref': None}
    curve = {'channel': 'gaze', 'body_part': 'eyes', 'controller_ref': 'pending:D5/gaze/object',
             'mapping_status': 'pending_D5', 'execution_status': 'unsupported',
             'unsupported_reason': 'D5 registry missing; proposal only', 'unit': 'degree',
             'target_ref': 'object-reveal',
             'phases': {'start_tick': 120, 'anticipation_end_tick': 180,
                        'arrival_end_tick': 240, 'hold_end_tick': 480, 'end_tick': 600},
             'timing': 'twos', 'interpolation': 'linear',
             'owner': {'kind': 'director', 'id': 'd4-director', 'authorization_ref': 'fixture-only'},
             'keyframes': [{'tick': 120, 'value': [0, 0]}, {'tick': 240, 'value': [20, 10]},
                           {'tick': 480, 'value': [20, 10]}, {'tick': 600, 'value': [0, 0]}]}
    response = {'protocol': 'hub.performance/v0', 'record_kind': 'response',
                'response_id': 'response-d4-independent', 'request_id': request['request_id'],
                'binding': copy.deepcopy(binding), 'curves': [curve],
                'unsupported': [{'path': '/curves/mouth', 'reason': 'No actual audio/alignment'}]}
    error = {'protocol': 'hub.performance/v0', 'record_kind': 'error',
             'request_id': request['request_id'],
             'errors': [{'code': 'missing_audio_alignment', 'path': '/audio_ref/alignment',
                         'message': 'No actual aligned audio; mouth unsupported.'}]}
    check('independent_request_no_audio', request, True)
    check('independent_response_pending_unsupported', response, True)
    aligned = copy.deepcopy(request); aligned['audio_ref'] = copy.deepcopy(audio)
    check('independent_request_aligned_audio_structure', aligned, True)
    for status in ['pending', 'failed']:
        data = copy.deepcopy(aligned); data['audio_ref']['alignment'] = {'status': status}
        check('independent_audio_' + status, data, True)
    data = copy.deepcopy(aligned); data['audio_ref']['offset_samples'] = 123
    check('positive_audio_offset', data, True)
    for code in ERRORS:
        data = copy.deepcopy(error); data['errors'][0]['code'] = code
        check('error_code_' + code, data, True)
    for path in ['', '/curves/0/owner', '/a~0b/~1escaped']:
        data = copy.deepcopy(error); data['errors'][0]['path'] = path
        check('json_pointer_' + repr(path), data, True)
    for name, data in [('null', None), ('old_bare_audio_string', 'fixture:audio')]:
        data2 = copy.deepcopy(request); data2['audio_ref'] = data
        check('audio_' + name, data2, data is None)
    for field in ['asset_ref', 'sha256', 'sample_rate', 'anchor_tick', 'offset_samples', 'alignment']:
        data = copy.deepcopy(aligned); del data['audio_ref'][field]
        check('reject_audio_missing_' + field, data, False)
    for field, value in [('asset_ref', ''), ('sha256', '0' * 63), ('sha256', 'g' * 64),
                         ('sample_rate', 0), ('sample_rate', -1), ('sample_rate', 44100.5),
                         ('sample_rate', '44100'), ('anchor_tick', -1),
                         ('anchor_tick', 120.5), ('offset_samples', -0.5), ('offset_samples', '0')]:
        data = copy.deepcopy(aligned); data['audio_ref'][field] = value
        check('reject_audio_bad_' + field + '_' + str(value)[:18], data, False)
    for field in ['ref', 'sha256']:
        data = copy.deepcopy(aligned); del data['audio_ref']['alignment'][field]
        check('reject_aligned_missing_' + field, data, False)
    for field, value in [('status', 'success'), ('ref', ''), ('sha256', 'BAD')]:
        data = copy.deepcopy(aligned); data['audio_ref']['alignment'][field] = value
        check('reject_bad_alignment_' + field, data, False)
    data = copy.deepcopy(aligned); data['audio_ref']['alignment']['unexpected'] = 'x'
    check('reject_alignment_unknown_field', data, False)
    data = copy.deepcopy(aligned); data['audio_ref']['duration'] = 1
    check('reject_audio_unknown_field', data, False)
    for field in ['protocol', 'record_kind', 'request_id', 'errors']:
        data = copy.deepcopy(error); del data[field]
        check('reject_error_missing_' + field, data, False)
    data = copy.deepcopy(error); data['errors'] = []
    check('reject_empty_errors', data, False)
    for field in ['code', 'path', 'message']:
        data = copy.deepcopy(error); del data['errors'][0][field]
        check('reject_error_item_missing_' + field, data, False)
    for field, value in [('code', 'not_registered'), ('message', ''), ('path', 'curves/0')]:
        data = copy.deepcopy(error); data['errors'][0][field] = value
        check('reject_error_bad_' + field, data, False)
    data = copy.deepcopy(error); data['curves'] = [copy.deepcopy(curve)]
    check('reject_error_plus_success_curves', data, False)
    data = copy.deepcopy(error); data['binding'] = copy.deepcopy(binding)
    check('reject_error_plus_binding', data, False)
    data = copy.deepcopy(response); data['curves'][0]['execution_status'] = 'candidate'
    check('reject_pending_D5_candidate', data, False)
    data = copy.deepcopy(response); data['curves'][0]['execution_status'] = 'executed'
    check('reject_any_claim_executed', data, False)
    data = copy.deepcopy(response); data['curves'][0]['controller_ref'] = 'real/controller'
    check('reject_pending_D5_nonpending_controller', data, False)
    data = copy.deepcopy(response); data['curves'][0]['mapping_status'] = 'registered'
    check('reject_registered_pending_D5_controller', data, False)
    data = copy.deepcopy(response); del data['curves'][0]['unsupported_reason']
    check('reject_pending_missing_unsupported_reason', data, False)
    for field in ['kind', 'id', 'authorization_ref']:
        data = copy.deepcopy(response); del data['curves'][0]['owner'][field]
        check('reject_owner_missing_' + field, data, False)
    data = copy.deepcopy(response); data['curves'][0]['owner']['kind'] = 'world_brain'
    check('reject_owner_unknown_kind', data, False)
    data = copy.deepcopy(response); data['curves'][0]['owner_id'] = 'legacy'
    check('reject_legacy_owner_id', data, False)
    data = copy.deepcopy(response); data['curves'][0]['owner']['effective_interval'] = [120, 600]
    check('reject_separate_owner_interval', data, False)
    for hz in [24, 60, 121]:
        data = copy.deepcopy(request); data['binding']['sim_hz'] = hz
        check('reject_sim_hz_' + str(hz), data, False)
    for field in binding:
        data = copy.deepcopy(request); del data['binding'][field]
        check('reject_missing_binding_' + field, data, False)
    data = copy.deepcopy(response); data['curves'][0]['timing'] = '2_ticks'
    check('reject_tick_based_timing_enum', data, False)
    for idx, example in enumerate(s.get('examples', [])):
        check('author_embedded_example_' + str(idx), example, True)

    # The following intentionally demonstrate that structure is not execution admission.
    data = copy.deepcopy(response); data['curves'][0]['phases']['arrival_end_tick'] = 121
    semantic_probe('unordered_phases', data, 'invalid_time_curve')
    data = copy.deepcopy(response); data['curves'][0]['keyframes'][1]['tick'] = 120
    semantic_probe('duplicate_keyframe_tick', data, 'invalid_time_curve')
    data = copy.deepcopy(response); data['curves'][0]['keyframes'] = data['curves'][0]['keyframes'][1:]
    semantic_probe('keyframes_do_not_cover_start', data, 'invalid_time_curve')
    data = copy.deepcopy(response); other = copy.deepcopy(curve); other['owner']['id'] = 'second-director'; data['curves'].append(other)
    semantic_probe('same_interval_two_owners', data, 'control_conflict')
    data = copy.deepcopy(response); data['binding']['world_version'] += 1
    semantic_probe('request_response_binding_mismatch', data, 'stale_revision / binding check', request)
    data = copy.deepcopy(response); data['curves'][0]['keyframes'][1]['value'] = [float('nan'), 1]
    # Not serialized as JSON: NaN is outside JSON; the Python validator still needs semantic finite checks.
    probes.append({'case': 'nonfinite_Python_instance', 'schema_accepts': validator.is_valid(data),
                   'future_semantic_requirement': 'All numeric values finite; strict JSON parsing and D2 finite checks.',
                   'interpretation': 'Non-JSON Python object probe only; not an admitted JSON fixture.'})
    for audio_status in ['none', 'pending', 'failed']:
        req = copy.deepcopy(request)
        if audio_status != 'none':
            req['audio_ref'] = copy.deepcopy(audio)
            req['audio_ref']['alignment'] = {'status': audio_status}
        data = copy.deepcopy(response)
        data['curves'][0].update(channel='mouth', body_part='mouth', controller_ref='d4-fixture/registered/mouth',
                                 mapping_status='registered', execution_status='candidate')
        semantic_probe('mouth_without_trusted_alignment_' + audio_status, data,
                       'mouth unsupported; missing_audio_alignment', req)
    data = copy.deepcopy(aligned); data['audio_ref']['sha256'] = '0' * 64
    semantic_probe('syntactically_valid_but_false_audio_digest', data,
                   'resolve bytes and compare exact digest; missing_audio_alignment/unsupported')
    data = copy.deepcopy(error); data['errors'][0]['path'] = '/bad~2escape'
    semantic_probe('invalid_JSON_Pointer_escape', data,
                   'Path must be a JSON Pointer; current pattern checks only leading slash.')

    # Pure rational arithmetic checks the written formula, not a clock adapter implementation.
    clock_rows = []
    def sample(tick):
        return Fraction(audio['offset_samples']) + Fraction((tick - audio['anchor_tick']) * audio['sample_rate'], 120)
    for tick, expected in [(120, Fraction(-2205)), (121, Fraction(-3675, 2)),
                           (126, Fraction(0)), (240, Fraction(41895))]:
        actual = sample(tick)
        clock_rows.append({'tick': tick, 'sample': str(actual), 'expected': str(expected), 'pass': actual == expected})
    clock_rows.append({'fps': 24, 'timing': 'twos', 'ticks_per_hold': str(Fraction(120 * 2, 24)),
                       'expected': '10', 'pass': Fraction(120 * 2, 24) == 10})
    paths = [SCHEMA, DOC, R1 / 'r1-performance_interface_v0.md',
             R1 / 'r1-performance_interface_v0.schema.json', R1 / 'report.md',
             R1 / 'identities.json', R1 / 'structure-checks.json',
             RELAY / 'reports/V-tier1-design-bundle-20261015/grokbot-k7q2-review.md']
    identities = [sha(p) for p in paths]
    author_ids = json.loads((R1 / 'identities.json').read_text())
    current = {r['path']: r for r in identities}
    author_hash_match = all(current[r['path']]['sha256'] == r['sha256'] and
                            current[r['path']]['bytes'] == r['bytes'] for r in author_ids)
    r1_hash_match = (sha(paths[2])['sha256'] == 'e251d79c42e4152a284e9d2249d5684248fc21b2c76b7b0d21a616595df70591'
                     and sha(paths[3])['sha256'] == '2e3b6546ccb74c068e25cee8d7fb8532973ef98765ff8e21135fcbb64fd97676')
    actual_codes = s['oneOf'][2]['properties']['errors']['items']['properties']['code']['enum']
    checks = {'author_r2_hash_match': author_hash_match, 'r1_archive_hash_match': r1_hash_match,
              'exact_ten_error_codes': actual_codes == ERRORS,
              'doc_owner_object_named': all(x in DOC.read_text() for x in ['owner.kind', 'owner.id', 'owner.authorization_ref']),
              'request_response_binding_schema_equal': s['oneOf'][0]['properties']['binding'] == s['oneOf'][1]['properties']['binding'],
              'no_model_imports': not any(x.split('.')[0] in {'mlx', 'torch', 'tensorflow'} for x in sys.modules)}
    if args.failure_control:
        check('intentional_failure_control', request, False)
    failed = sum(not r['pass'] for r in rows) + sum(not x for x in checks.values()) + sum(not x['pass'] for x in clock_rows)
    result = {'scope': 'independent structure and document/formula audit only',
              'python': sys.version, 'jsonschema': version('jsonschema'), 'schema_meta_valid': True,
              'structure_passed': sum(r['pass'] for r in rows), 'structure_total': len(rows),
              'checks': checks, 'clock_arithmetic': clock_rows,
              'semantic_probes_count': len(probes), 'semantic_probes_all_schema_accepted': all(p['schema_accepts'] for p in probes),
              'failed': failed, 'tests': rows, 'identities': identities}
    suffix = '-failure-control' if args.failure_control else ''
    for name, data in [('results', result), ('cases', cases), ('semantic-boundaries', probes)]:
        (OUT / (name + suffix + '.json')).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print(json.dumps({k: result[k] for k in ['scope', 'jsonschema', 'structure_passed', 'structure_total', 'checks', 'clock_arithmetic', 'failed']}, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
