"""
Shared dependency utilities for routers.

Responsibilities:
- Fetch authenticated user from session
- Enforce authentication
- (Optional) enforce roles

Must NOT:
- Perform DB access
- Write audit logs
"""

from fastapi import Request, HTTPException, status


# ======================================================
# BASE AUTH DEPENDENCY
# ======================================================

def get_current_user(request: Request) -> dict:
    """
    Returns the current authenticated user from session.

    Raises:
        HTTPException(401) if user is not authenticated
    """
    user = request.session.get("user")
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user


# ======================================================
# ROLE-BASED DEPENDENCIES (EXTENSIBLE)
# ======================================================

def require_admin_user(request: Request) -> dict:
    """
    Ensures the user is authenticated AND is an admin.
    """
    user = get_current_user(request)
    if not user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return user
