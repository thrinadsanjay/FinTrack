from fastapi import APIRouter

router = APIRouter()

@router.get("/me")
def read_me():
    return {"message": "Cat router working"}
