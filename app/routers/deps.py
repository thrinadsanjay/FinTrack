from fastapi import Request, HTTPException

def get_current_session_user(request: Request):
    token = request.session.get("user")
    if not token:
        raise HTTPException(status_code=401)
    return token

def get_current_api_user(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user