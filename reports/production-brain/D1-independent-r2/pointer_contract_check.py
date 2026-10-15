#!/usr/bin/env python3
"""Fail-loud regression for the remaining error.path contract mismatch."""
import json
import sys
from pathlib import Path
from jsonschema import Draft202012Validator

ROOT = Path('/Users/mac/AinerWorkFlow/AinerHub_IDEA')
OUT = ROOT / 'reports/production-brain/D1-independent-r2'
schema = json.loads((ROOT / 'docs/v2/production_brain/performance_interface_v0.schema.json').read_text())
validator = Draft202012Validator(schema)
rows = []
for pointer, expected in [('', True), ('/curves/0', True), ('/a~0b/~1escaped', True),
                          ('/bad~2escape', False), ('/bad~', False), ('curves/0', False)]:
    instance = {'protocol': 'hub.performance/v0', 'record_kind': 'error',
                'request_id': 'independent-pointer-check',
                'errors': [{'code': 'invalid_time_curve', 'path': pointer, 'message': 'Fixture only.'}]}
    actual = validator.is_valid(instance)
    rows.append({'pointer': pointer, 'expected_valid': expected, 'actual_valid': actual,
                 'pass': actual == expected, 'instance': instance})
result = {'passed': sum(x['pass'] for x in rows), 'total': len(rows), 'cases': rows}
(OUT / 'pointer-contract-results.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
sys.exit(0 if all(x['pass'] for x in rows) else 1)
