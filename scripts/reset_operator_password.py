"""Set a new local operator password without printing it or its hash."""

from getpass import getpass
import os
from pathlib import Path
import re
import tempfile

from app.services.passwords import hash_password


ENV_PATH = Path(__file__).resolve().parents[1] / '.env'


def reset_password(env_path, password, confirmation):
    if password != confirmation:
        raise ValueError('Passwords must match. Nothing was changed.')
    new_hash = hash_password(password)
    path = Path(env_path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('A regular local .env file is required. Nothing was changed.')
    with path.open('r', encoding='utf-8', newline='') as source:
        original = source.read()
    pattern = re.compile(r'^[ \t]*(?:export[ \t]+)?OPERATOR_PASSWORD_HASH[ \t]*=[^\r\n]*', re.MULTILINE | re.IGNORECASE)
    if len(pattern.findall(original)) > 1:
        raise ValueError('Multiple password entries found. Fix duplicate entries before resetting.')
    replacement = 'OPERATOR_PASSWORD_HASH=' + new_hash
    if pattern.search(original):
        updated = pattern.sub(lambda match: replacement, original)
    else:
        newline = '\r\n' if '\r\n' in original else '\n'
        updated = original + ('' if not original or original.endswith(('\r', '\n')) else newline) + replacement + newline
    temporary = None
    try:
        # Keep temporary credential data beside .env on the same drive.
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='',
                                         dir=path.parent, prefix='.operator-reset-', delete=False) as output:
            temporary = Path(output.name)
            output.write(updated)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main():
    password = getpass('New password (12 to 1024 characters; typing stays hidden): ')
    confirmation = getpass('Confirm new password: ')
    try:
        reset_password(ENV_PATH, password, confirmation)
    except (ValueError, OSError):
        raise SystemExit('Password reset could not complete. Check matching passwords, length, and local .env access.') from None
    print('Password updated locally. Username unchanged. Restart RecoverAI to use the new password.')


if __name__ == '__main__':
    main()
