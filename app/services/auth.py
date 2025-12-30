from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt
from app.core.config import settings
from app.core.security import get_jwks
from app.services.users import get_oauth_user, create_oauth_user, update_user_password

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

async def handle_keycloak_user(oauth_sub: str, email: str):
    user = await get_oauth_user(oauth_sub)

    if not user:
        user = await create_oauth_user(
            oauth_sub=oauth_sub,
            email=email,
        )

    return user


