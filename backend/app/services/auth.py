from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from app.core.config import settings
from app.core.security import get_jwks
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.services.user import get_or_create_user

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db),):
    # try:
    #     jwks = get_jwks()
    payload = jwt.decode(
        token,
        get_jwks(),
        algorithms=["RS256"],
        #options={"verify_aud": False}, 
        audience=settings.KEYCLOAK_CLIENT_ID,
        issuer=f"{settings.KEYCLOAK_URL}/realms/{settings.KEYCLOAK_REALM}",
    )

    user = get_or_create_user(db, payload)
    return user
    #     return payload
    # except JWTError:
    #     raise HTTPException(
    #         status_code=status.HTTP_401_UNAUTHORIZED,
    #         detail="Invalid token",
    #     )
