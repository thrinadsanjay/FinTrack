from app.db.mongo import db

async def get_or_create_user(token_payload: dict):
    keycloak_id = token_payload["sub"]

    user = await db.users.find_one({"keycloak_id": keycloak_id})
    if user:
        return user

    user_doc = {
        "keycloak_id": keycloak_id,
        "email": token_payload.get("email"),
        "username": token_payload.get("preferred_username"),
    }

    result = await db.users.insert_one(user_doc)
    user_doc["_id"] = result.inserted_id
    return user_doc
