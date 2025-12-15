from sqlalchemy.orm import Session
from app.models.user import User


def get_or_create_user(db: Session, token_payload: dict) -> User:
    keycloak_id = token_payload["sub"]
    email = token_payload.get("email")
    username = token_payload.get("preferred_username")

    user = (
        db.query(User)
        .filter(User.keycloak_id == keycloak_id)
        .first()
    )

    if user:
        # Optional: update email/username if changed
        user.email = email
        user.username = username
        return user

    user = User(
        keycloak_id=keycloak_id,
        email=email,
        username=username,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return user
