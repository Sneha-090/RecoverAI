"""Create a password hash locally: python -m scripts.hash_password."""

from getpass import getpass
from app.services.passwords import hash_password


def main():
    password = getpass("New operator password (at least 12 characters): ")
    confirmation = getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords must match")
    try:
        print(hash_password(password))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
