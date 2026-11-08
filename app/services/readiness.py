"""Infrastructure readiness with controlled error codes and no provider API calls."""

import hashlib
import json
from pathlib import Path

from sqlalchemy import text

from app.db.session import engine
from app.db.schema import schema_status
from app.services.operator_auth import auth_configured

ROOT=Path(__file__).resolve().parents[2]


def check_readiness(bind=None,root=None):
    bind=bind or engine;root=Path(root) if root else ROOT;issues=[]
    if not auth_configured():issues.append('operator_not_configured')
    try:
        with bind.connect() as connection:connection.execute(text('SELECT 1'))
        if not schema_status(bind)['is_current']:issues.append('schema_outdated')
    except Exception:issues.append('database_unavailable')
    try:
        report=json.loads((root/'ML/evaluation.json').read_text(encoding='utf-8'))
        if hashlib.sha256((root/'ML/recovery_model.joblib').read_bytes()).hexdigest()!=report['model_sha256']:
            issues.append('model_artifact_mismatch')
    except Exception:issues.append('model_artifact_unavailable')
    return {'status':'ready' if not issues else 'not_ready','issues':issues}
