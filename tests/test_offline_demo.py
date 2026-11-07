import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from scripts.offline_demo import run_scenarios
from scripts.demo_provider import DemoProvider
from scripts.render_demo_html import render_demo_html


ROOT = Path(__file__).resolve().parents[1]


def test_offline_demo_is_repeatable_and_never_modifies_existing_env_or_merchant_db(tmp_path):
    merchant = tmp_path/'merchant.sqlite'
    with sqlite3.connect(merchant) as db:
        db.execute('create table keep_me (value text)')
        db.execute("insert into keep_me values ('unchanged')")
    dotenv = tmp_path/'.env'; dotenv.write_text('RAZORPAY_KEY_SECRET=private_dummy\n')
    original_db = hashlib.sha256(merchant.read_bytes()).hexdigest()
    original_env = dotenv.read_bytes()
    env = os.environ.copy()
    env.update(PYTHONPATH=str(ROOT),PYTHONDONTWRITEBYTECODE='1',
               DATABASE_URL=f'sqlite:///{merchant.as_posix()}',
               RAZORPAY_KEY_ID='rzp_live_must_not_be_used',RAZORPAY_KEY_SECRET='private_sentinel')
    reports = []
    for run in range(2):
        output = tmp_path/f'report{run}'
        result = subprocess.run([sys.executable,'-m','scripts.offline_demo' if run == 0 else 'scripts.live_demo','--output-dir',str(output),
            '--work-dir',str(tmp_path/'runs')],cwd=tmp_path,env=env,capture_output=True,text=True,timeout=60)
        assert result.returncode == 0, result.stderr
        assert 'private_sentinel' not in result.stdout+result.stderr
        report = json.loads((output/'offline_demo.json').read_text())
        assert report['passed'] == 6 and report['not_a_live_provider_test'] is True
        assert (output/'offline_demo.html').exists()
        by_id = {row['payment_id']:row for row in report['scenarios']}
        assert by_id['pay_DemoNormal']['provider_creations'] == 1
        assert by_id['pay_DemoNormal']['duplicate_status'] == 'already_processed'
        assert by_id['pay_DemoNormal']['invalid_signature_http'] == 400
        assert by_id['pay_DemoLostResponse']['provider_creations'] == 1
        assert by_id['pay_DemoLostResponse']['final_status'] == 'recovered'
        assert by_id['pay_DemoExpiry']['provider_creations'] == 0
        assert by_id['pay_DemoExpiry']['final_status'] == 'closed_unrecovered'
        assert by_id['pay_DemoLateCapture']['outcomes'] == 1
        assert by_id['pay_DemoEarlyCapture']['replay_processed'] == 1
        assert all(row['reservation'] is None for row in report['scenarios'])
        reports.append(report)
    assert reports[0] == reports[1]
    assert len(list((tmp_path/'runs').glob('offline_*.sqlite'))) == 2
    assert hashlib.sha256(merchant.read_bytes()).hexdigest() == original_db
    assert dotenv.read_bytes() == original_env


def test_imported_app_configuration_cannot_be_reused_for_demo(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, 'app.config', object())
    with pytest.raises(RuntimeError,match='fresh process'):
        run_scenarios(tmp_path/'never_created.sqlite')
    assert not (tmp_path/'never_created.sqlite').exists()


def test_fake_response_loss_happens_after_creation_and_keeps_intent_reference():
    provider = DemoProvider(); provider.lose_next_response = True
    with pytest.raises(TimeoutError):
        provider.create_link({'amount':49900,'currency':'INR','notes':{'recoverai_intent_id':'fixture'}})
    assert provider.creations == 1
    assert provider.fetch_link(provider.last_created[1])['notes']['recoverai_intent_id'] == 'fixture'


def test_rendered_replay_is_self_contained_and_escapes_embedded_data():
    report = {'scenarios':[], 'label':'</script><script>bad()</script>'}
    html = render_demo_html(report)
    assert 'src="http' not in html and 'href="http' not in html
    assert '</script><script>bad()' not in html
    assert 'Buttons replay a recorded run' in html
    assert 'no merchant revenue claim' in html.lower()
