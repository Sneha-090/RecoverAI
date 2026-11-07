"""Read recorded benchmark evidence and reject stale inputs or source code."""

import json
from pathlib import Path

from app.services.artifact_hashes import text_sha256


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT = ROOT/'reports/policy_benchmark.json'


def load_benchmark_report(path=None, root=None):
    path = Path(path) if path else DEFAULT_REPORT
    root = Path(root) if root else ROOT
    report = json.loads(path.read_text(encoding='utf-8'))
    if report.get('schema_version') != 1:
        raise ValueError('Unsupported benchmark report version')
    checks = {'dataset_sha256':root/'data/synthetic_payments.csv',
              'benchmark_code_sha256':root/'ML/benchmark_policies.py',
              'selector_code_sha256':root/'app/services/policy.py',
              'training_code_sha256':root/'ML/train_model.py',
              'decisions_sha256':path.parent/'policy_decisions.csv'}
    if any(report.get(key) != text_sha256(source) for key, source in checks.items()):
        raise ValueError('Benchmark evidence is stale; regenerate it before displaying metrics')
    if not report.get('splits') or any(split['overlapping_contexts'] != 0 for split in report['splits']):
        raise ValueError('Benchmark does not have disjoint context splits')
    if not any(split['seed'] == report['primary_seed'] for split in report['splits']):
        raise ValueError('Primary split is missing')
    return report
