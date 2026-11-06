from unittest.mock import Mock

import pytest

from app.services.review_maintenance import maintain_reviews
from scripts import maintain_reviews as command


class SessionContext:
    def __init__(self, session):
        self.session = session
    def __enter__(self):
        return self.session
    def __exit__(self, *args):
        return False


def test_maintenance_uses_bounded_expiry_pass_and_returns_count(monkeypatch):
    session = Mock()
    expiry = Mock(return_value=[object(), object()])
    monkeypatch.setattr('app.services.review_maintenance.expire_overdue_reviews', expiry)
    assert maintain_reviews(limit=7, session_factory=lambda: SessionContext(session)) == {'expired': 2}
    expiry.assert_called_once_with(session, limit=7)


def test_single_batch_prints_result(monkeypatch, capsys):
    task = Mock(return_value={'expired': 2})
    monkeypatch.setattr(command, 'maintain_reviews', task)
    command.main(['--limit', '7'])
    task.assert_called_once_with(limit=7)
    assert capsys.readouterr().out.strip() == '{"expired": 2}'


def test_idle_watch_stays_quiet_and_stops_cleanly(monkeypatch, capsys):
    task = Mock(return_value={'expired': 0})
    monkeypatch.setattr(command, 'maintain_reviews', task)
    monkeypatch.setattr(command.time, 'sleep', Mock(side_effect=KeyboardInterrupt))
    command.main(['--watch'])
    assert task.call_count == 1
    assert capsys.readouterr().out == ''


def test_watch_reports_sanitized_error_then_retries(monkeypatch, capsys):
    task = Mock(side_effect=[RuntimeError('PRIVATE_CONNECTION_SECRET'), {'expired': 1}])
    monkeypatch.setattr(command, 'maintain_reviews', task)
    monkeypatch.setattr(command.time, 'sleep', Mock(side_effect=[None, KeyboardInterrupt]))
    command.main(['--watch', '--interval', '1'])
    output = capsys.readouterr().out
    assert task.call_count == 2
    assert 'PRIVATE_CONNECTION_SECRET' not in output
    assert '"expired": 1' in output


def test_single_batch_failure_is_sanitized(monkeypatch):
    monkeypatch.setattr(command, 'maintain_reviews', Mock(side_effect=RuntimeError('PRIVATE_CONNECTION_SECRET')))
    with pytest.raises(SystemExit) as result:
        command.main([])
    assert 'PRIVATE_CONNECTION_SECRET' not in str(result.value)


@pytest.mark.parametrize('arguments', [['--limit', '0'], ['--limit', '1001'], ['--interval', '0']])
def test_cli_rejects_unbounded_arguments(arguments):
    with pytest.raises(SystemExit) as result:
        command.main(arguments)
    assert result.value.code == 2
