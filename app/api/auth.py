from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.services.operator_auth import auth_configured, verify_operator


basic = HTTPBasic(auto_error=False)


def require_operator(credentials: Annotated[HTTPBasicCredentials | None, Depends(basic)]) -> str:
    if not auth_configured():
        raise HTTPException(status_code=503, detail="Operator authentication is not configured")
    if credentials is None or not verify_operator(credentials.username, credentials.password):
        raise HTTPException(
            status_code=401, detail="Invalid operator credentials",
            headers={"WWW-Authenticate": 'Basic realm="RecoverAI"'},
        )
    return credentials.username
