from unittest.mock import Mock

import pytest

from scripts import reset_operator_password as reset
from app.services.passwords import verify_password


PASSWORD = 'local-reset-test-password'


@pytest.mark.parametrize('existing', [True, False])
def test_reset_updates_only_password_and_preserves_other_values(tmp_path, existing):
    env = tmp_path / '.env'
    original = 'OPERATOR_USERNAME=sneha\r\nRAZORPAY_KEY_SECRET=private_dummy\r\n'
    if existing:
        original += 'OPERATOR_PASSWORD_HASH=old_hash\r\n'
    env.write_bytes(original.encode())
    reset.reset_password(env, PASSWORD, PASSWORD)
    updated = env.read_bytes().decode()
    assert 'OPERATOR_USERNAME=sneha\r\nRAZORPAY_KEY_SECRET=private_dummy\r\n' in updated
    hashes = [line.split('=', 1)[1] for line in updated.splitlines() if line.startswith('OPERATOR_PASSWORD_HASH=')]
    assert len(hashes) == 1
    assert verify_password(PASSWORD, hashes[0])
    assert PASSWORD not in updated
    assert not list(tmp_path.glob('.operator-reset-*'))


@pytest.mark.parametrize('password,confirmation', [('short', 'short'), (PASSWORD, 'different')])
def test_invalid_password_leaves_env_unchanged(tmp_path, password, confirmation):
    env = tmp_path / '.env'
    env.write_text('OPERATOR_PASSWORD_HASH=existing\n')
    with pytest.raises(ValueError):
        reset.reset_password(env, password, confirmation)
    assert env.read_text() == 'OPERATOR_PASSWORD_HASH=existing\n'


def test_ambiguous_entries_are_not_overwritten(tmp_path):
    env = tmp_path / '.env'
    original = 'OPERATOR_PASSWORD_HASH=one\nexport OPERATOR_PASSWORD_HASH=two\n'
    env.write_text(original)
    with pytest.raises(ValueError):
        reset.reset_password(env, PASSWORD, PASSWORD)
    assert env.read_text() == original


def test_failed_atomic_replace_preserves_original_and_cleans_temp(tmp_path, monkeypatch):
    env = tmp_path / '.env'
    env.write_text('OPERATOR_PASSWORD_HASH=existing\n')
    monkeypatch.setattr(reset.os, 'replace', Mock(side_effect=OSError('failure')))
    with pytest.raises(OSError):
        reset.reset_password(env, PASSWORD, PASSWORD)
    assert env.read_text() == 'OPERATOR_PASSWORD_HASH=existing\n'
    assert not list(tmp_path.glob('.operator-reset-*'))


def test_cli_never_prints_password_or_hash(tmp_path, monkeypatch, capsys):
    env = tmp_path / '.env'
    env.write_text('OPERATOR_USERNAME=sneha\nOPERATOR_PASSWORD_HASH=existing\n')
    monkeypatch.setattr(reset, 'ENV_PATH', env)
    monkeypatch.setattr(reset, 'getpass', Mock(side_effect=[PASSWORD, PASSWORD]))
    reset.main()
    output = capsys.readouterr().out
    assert 'Password updated locally' in output
    assert PASSWORD not in output and 'pbkdf2' not in output


@pytest.mark.parametrize('password,confirmation,expected', [
    ('short', 'short', 'Use a password with 12 to 1024 characters'),
    ('x' * 1025, 'x' * 1025, 'Use a password with 12 to 1024 characters'),
    (PASSWORD, 'different', 'Passwords must match'),
])
def test_cli_explains_invalid_input_without_disclosing_it(tmp_path, monkeypatch, capsys,
                                                         password, confirmation, expected):
    env = tmp_path / '.env'
    original = 'OPERATOR_PASSWORD_HASH=existing\n'
    env.write_text(original)
    monkeypatch.setattr(reset, 'ENV_PATH', env)
    monkeypatch.setattr(reset, 'getpass', Mock(side_effect=[password, confirmation]))
    with pytest.raises(SystemExit) as error:
        reset.main()
    output = str(error.value) + capsys.readouterr().out
    assert expected in output
    assert password not in output and confirmation not in output
    assert 'pbkdf2' not in output
    assert env.read_text() == original


def test_cli_hides_filesystem_error_details(tmp_path, monkeypatch, capsys):
    env = tmp_path / '.env'
    original = 'OPERATOR_PASSWORD_HASH=existing\n'
    env.write_text(original)
    monkeypatch.setattr(reset, 'ENV_PATH', env)
    monkeypatch.setattr(reset, 'getpass', Mock(side_effect=[PASSWORD, PASSWORD]))
    monkeypatch.setattr(reset.os, 'replace', Mock(side_effect=OSError('private/path/secret')))
    with pytest.raises(SystemExit) as error:
        reset.main()
    output = str(error.value) + capsys.readouterr().out
    assert 'Check write permission and free disk space' in output
    assert 'private/path/secret' not in output and PASSWORD not in output
    assert 'pbkdf2' not in output
    assert env.read_text() == original
    assert not list(tmp_path.glob('.operator-reset-*'))


@pytest.mark.parametrize('contents,expected', [
    (None, 'A regular local .env file is required'),
    ('OPERATOR_PASSWORD_HASH=one\nOPERATOR_PASSWORD_HASH=two\n',
     'Multiple password entries found'),
])
def test_cli_explains_configuration_errors(tmp_path, monkeypatch, contents, expected):
    env = tmp_path / '.env'
    if contents is not None:
        env.write_text(contents)
    monkeypatch.setattr(reset, 'ENV_PATH', env)
    monkeypatch.setattr(reset, 'getpass', Mock(side_effect=[PASSWORD, PASSWORD]))
    with pytest.raises(SystemExit) as error:
        reset.main()
    assert expected in str(error.value)
    assert PASSWORD not in str(error.value)
    if contents is not None:
        assert env.read_text() == contents
    else:
        assert not env.exists()
