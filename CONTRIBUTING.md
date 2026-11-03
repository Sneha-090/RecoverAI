# Small, meaningful commits

The owner authorizes assistant commits and pushes. Keep independent improvements
in separate, tested commits. See `AGENTS.md` for the repository instruction.

Run commands from your working clone with its virtual environment activated.
Before staging, use `git status --short` and `git diff`; never stage `.env`, local
databases, or virtual environments. Each group below is a separate change with
its own relevant tests. Complete them in order because later groups depend on
earlier ones. You can push after each completed commit.

## 1. Password hashing and local setup helper

```cmd
python -m pytest tests/test_passwords.py -q
git add app/services/passwords.py scripts/hash_password.py tests/test_passwords.py
git commit -m "feat: add salted operator password hashing and setup helper"
git push origin main
```

## 2. Protected API and checkout

```cmd
python -m pytest tests/test_passwords.py tests/test_operator_auth.py -q
git add app/config.py app/api/auth.py app/services/operator_auth.py app/main.py scripts/checkout.html tests/test_operator_auth.py
git commit -m "feat: protect payment API and checkout with operator authentication"
git push origin main
```

## 3. Dashboard login and logout

```cmd
python -m pytest tests/test_dashboard_login.py -q
git add app/ui/__init__.py app/ui/operator_login.py dashboard.py tests/test_dashboard_login.py
git commit -m "feat: require operator login for dashboard and approvals"
git push origin main
```

## 4. Setup instructions, status, and contribution workflow

```cmd
python -m pytest -q
git add .env.example README.md ROADMAP.md AGENTS.md CONTRIBUTING.md
git commit -m "docs: explain operator setup and manual contribution workflow"
git push origin main
```

These examples describe coherent scopes for the authentication implementation.
The password helper can also be separated from the hashing library. Documentation
and workflow-policy updates can be committed independently. Do not rerun these
commands to recreate changes that are already committed. If a test fails, fix it
before committing that group.
