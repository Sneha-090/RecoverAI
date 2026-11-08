from pydantic import SecretStr
from sqlalchemy import create_engine

from app.config import settings
from app.db.schema import migrate_database
from app.services.readiness import check_readiness


def test_readiness_requires_current_schema_and_reports_no_credentials(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,'operator_username','operator')
    monkeypatch.setattr(settings,'operator_password_hash',SecretStr('private-not-returned'))
    engine=create_engine(f"sqlite:///{(tmp_path/'ready.sqlite').as_posix()}")
    result=check_readiness(engine)
    assert result=={'status':'not_ready','issues':['schema_outdated']}
    migrate_database(engine)
    assert check_readiness(engine)=={'status':'ready','issues':[]}
    assert 'private' not in str(result)
    engine.dispose()


def test_readiness_blocks_missing_model_artifacts_and_missing_operator(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,'operator_username','')
    engine=create_engine(f"sqlite:///{(tmp_path/'ready.sqlite').as_posix()}")
    migrate_database(engine)
    result=check_readiness(engine,root=tmp_path)
    assert set(result['issues'])=={'operator_not_configured','model_artifact_unavailable'}
    engine.dispose()


def test_public_gateway_does_not_expose_internal_readiness():
    from fastapi.testclient import TestClient
    from app.webhook_gateway import app
    assert TestClient(app).get('/ready').status_code==404
