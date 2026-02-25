from fastapi import APIRouter
from openai import OpenAI
import os

router = APIRouter(prefix="/chat", tags=["AI"])

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@router.post("/ai")
async def ai_chat(data: dict):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are FinTracker support assistant."},
            {"role": "user", "content": data["message"]}
        ]
    )

    return {
        "reply": response.choices[0].message.content
    }