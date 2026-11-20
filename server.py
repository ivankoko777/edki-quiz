import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent
PARENT_DIR = BASE_DIR.parent
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()


def resolve_questions_file() -> Optional[Path]:
    for candidate in (BASE_DIR / "questions.json", PARENT_DIR / "questions.json"):
        if candidate.exists():
            return candidate
    return None


def get_conn() -> psycopg.Connection:
    if not DATABASE_URL:
        raise RuntimeError("Не задано змінну оточення DATABASE_URL")
    return psycopg.connect(DATABASE_URL, autocommit=True)


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
            """
        )


app = FastAPI(title="EDKI Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class UserStatePayload(BaseModel):
    name: str = "Студент"
    history: List[Dict[str, Any]] = []
    usedIds: List[Any] = []
    activeSession: Optional[Dict[str, Any]] = None


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/questions")
def get_questions() -> List[Dict[str, Any]]:
    q_file = resolve_questions_file()
    if not q_file:
        raise HTTPException(status_code=404, detail="questions.json не знайдено")
    with open(q_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list) or not data:
        raise HTTPException(status_code=500, detail="База питань порожня")
    return data


@app.get("/api/state/{user_id}")
def get_state(user_id: str) -> Dict[str, Any]:
    clean_id = user_id.strip()
    if not clean_id:
        raise HTTPException(status_code=400, detail="Порожній ідентифікатор профілю")

    with get_conn() as conn:
        row = conn.execute(
            "SELECT state_json FROM users WHERE user_id = %s",
            (clean_id,),
        ).fetchone()

    if not row:
        return {
            "userId": clean_id,
            "name": "Студент",
            "history": [],
            "usedIds": [],
            "activeSession": None,
        }

    parsed = json.loads(row[0])
    parsed["userId"] = clean_id
    return parsed


@app.put("/api/state/{user_id}")
def save_state(user_id: str, payload: UserStatePayload) -> Dict[str, Any]:
    clean_id = user_id.strip()
    if not clean_id:
        raise HTTPException(status_code=400, detail="Порожній ідентифікатор профілю")

    state_data = {
        "userId": clean_id,
        "name": payload.name.strip() or "Студент",
        "history": payload.history,
        "usedIds": payload.usedIds,
        "activeSession": payload.activeSession,
    }

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO users (user_id, state_json, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT(user_id) DO UPDATE SET
                state_json = EXCLUDED.state_json,
                updated_at = NOW();
            """,
            (clean_id, json.dumps(state_data, ensure_ascii=False)),
        )

    return {"status": "saved", "state": state_data}