import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import urlopen

import bcrypt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from database import get_db
from models import Employee


load_dotenv(Path(__file__).with_name(".env"))

SECRET_KEY = os.getenv("JWT_SECRET", "nss-pms-secret-key-2025")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = int(os.getenv("ACCESS_TOKEN_EXPIRE_HOURS", "24"))
AUTH_MODE = os.getenv("AUTH_MODE", "local").lower()

MICROSOFT_ENTRA_TENANT_ID = os.getenv("MICROSOFT_ENTRA_TENANT_ID", "842e4e0e-1c63-4147-b5bc-2b8baed2f998")
MICROSOFT_ENTRA_CLIENT_ID = os.getenv("MICROSOFT_ENTRA_CLIENT_ID", "b9df5b4b-d3f7-4e7c-9b31-9f3d183f180d")
MICROSOFT_OPENID_CONFIG_URL = (
    f"https://login.microsoftonline.com/{MICROSOFT_ENTRA_TENANT_ID}/v2.0/.well-known/openid-configuration"
)

security = HTTPBearer()


def hash_password(plain):
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain, hashed):
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(data, expires_delta=None):
    to_encode = data.copy()
    to_encode["exp"] = datetime.utcnow() + (expires_delta or timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS))
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def _fetch_json(url: str):
    with urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def validate_microsoft_id_token(id_token: str):
    if AUTH_MODE != "sso":
        raise HTTPException(status_code=400, detail="Microsoft SSO is disabled for this environment")

    try:
        openid_config = _fetch_json(MICROSOFT_OPENID_CONFIG_URL)
        jwks = _fetch_json(openid_config["jwks_uri"])
        claims = jwt.decode(
            id_token,
            jwks,
            algorithms=["RS256"],
            audience=MICROSOFT_ENTRA_CLIENT_ID,
            issuer=openid_config["issuer"],
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid Microsoft token: {exc}")

    if claims.get("tid") != MICROSOFT_ENTRA_TENANT_ID:
        raise HTTPException(status_code=401, detail="Microsoft tenant mismatch")

    email = claims.get("preferred_username") or claims.get("email") or claims.get("upn")
    if not email:
        raise HTTPException(status_code=401, detail="Microsoft token did not include a usable email")

    claims["resolved_email"] = email.lower()
    return claims


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        eid = payload.get("sub")
        if not eid:
            raise HTTPException(status_code=401, detail="Invalid token")
        user = db.query(Employee).filter(Employee.id == eid, Employee.is_active == True).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


def require_role(*roles):
    def checker(current_user: Employee = Depends(get_current_user)):
        if current_user.role.value not in [r.value if hasattr(r, "value") else r for r in roles]:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user
    return checker
