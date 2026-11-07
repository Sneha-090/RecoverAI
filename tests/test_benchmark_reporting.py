import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from app.services.artifact_hashes import text_sha256
from app.services.benchmark_reporting import load_benchmark_report


ROOT = Path(__file__).resolve().parents[1]


def test_text_fingerprint_is_portable_across_windows_and_linux(tmp_path):
    windows, linux = tmp_path/'windows.txt', tmp_path/'linux.txt'
    windows.write_bytes(b'a\r\nb\r\n'); linux.write_bytes(b'a\nb\n')
    assert text_sha256(windows) == text_sha256(linux)
    assert text_sha256(windows) == hashlib.sha256(b'a\nb\n').hexdigest()


def test_committed_evidence_loads_and_stale_input_is_rejected(tmp_path):
    report = load_benchmark_report()
    assert report['primary_seed'] == 42
    report['dataset_sha256'] = 'not-the-current-dataset'
    path = tmp_path/'policy_benchmark.json'; path.write_text(json.dumps(report))
    (tmp_path/'policy_decisions.csv').write_bytes((ROOT/'reports/policy_decisions.csv').read_bytes())
    with pytest.raises(ValueError,match='stale'):
        load_benchmark_report(path)


def test_dashboard_shows_actual_uncertainty_and_deferred_review_limits():
    app = AppTest.from_string('from app.ui.policy_benchmark import render_policy_benchmark\nrender_policy_benchmark()').run(timeout=20)
    assert not app.exception
    assert any('Synthetic evidence only' in item.value for item in app.warning)
    assert any('does not establish a clear ML advantage' in item.value for item in app.info)
    assert any('Deferred human reviews remain unresolved' in item.value for item in app.caption)
    table = app.dataframe[0].value
    assert len(table) == 4
    assert table['Interventions'].max() <= 400
    assert 'ML with review guardrails' in table['Policy'].tolist()


def test_stale_evidence_hides_metrics(monkeypatch):
    monkeypatch.setattr('app.ui.policy_benchmark.load_benchmark_report', Mock(side_effect=ValueError('stale')))
    app = AppTest.from_string('from app.ui.policy_benchmark import render_policy_benchmark\nrender_policy_benchmark()').run(timeout=15)
    assert not app.exception and app.error
    assert len(app.dataframe) == 0


def test_missing_report_has_reproduction_instruction(monkeypatch):
    monkeypatch.setattr('app.ui.policy_benchmark.load_benchmark_report', Mock(side_effect=FileNotFoundError))
    app = AppTest.from_string('from app.ui.policy_benchmark import render_policy_benchmark\nrender_policy_benchmark()').run(timeout=15)
    assert not app.exception
    assert any('python -m ML.benchmark_policies' in item.value for item in app.info)
