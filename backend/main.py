"""Nordic Atlas Cloud Run Backend — Single-User Google Auth, Structured Cloud Audit Logs & Streaming Agents."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from pydantic import BaseModel, Field

from agents import RESEARCH_MODEL, SYNTH_MODEL, run_parallel_research
from github_sync import (
    delete_custom_adventure_from_github,
    is_github_sync_enabled,
    save_custom_adventure_to_github,
)

# ---------- Configuration ----------
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
ALLOWED_EMAILS = {
    e.strip().lower()
    for e in os.getenv("ALLOWED_EMAILS", "matthewgfinley@gmail.com").split(",")
    if e.strip()
}
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS",
        "https://gfinley.github.io,http://localhost:8080,http://127.0.0.1:8080",
    ).split(",")
    if o.strip()
]
APP_ENV = os.getenv("APP_ENV", "prod").strip()

# ---------- Structured Cloud Logging Audit Helper ----------
def audit_log(event: str, severity: str = "INFO", **fields: Any) -> None:
    """Emit structured JSON to stdout for automatic Google Cloud Logging ingestion & auditing."""
    record = {
        "severity": severity,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "app": "nordic-atlas",
        "component": "adventure-advisor-agents",
        "env": APP_ENV,
        "owner": "gfinley",
        "event": event,
        **fields,
    }
    sys.stdout.write(json.dumps(record, ensure_ascii=False) + "\n")
    sys.stdout.flush()


app = FastAPI(
    title="Nordic Atlas Agentic Backend",
    version="1.1.0",
    docs_url=None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


# ---------- Single-User Google Sign-In Verification ----------
def verify_google_owner(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict:
    """Cryptographically verify a Google Sign-In ID token and enforce owner email allowlist."""
    path = request.url.path
    if not GOOGLE_CLIENT_ID:
        audit_log("auth_config_error", severity="ERROR", path=path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Backend GOOGLE_CLIENT_ID is not configured.",
        )

    if not authorization or not authorization.startswith("Bearer "):
        audit_log("auth_denied", severity="WARNING", reason="missing_bearer", path=path)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Google Sign-In Bearer token.",
        )

    token = authorization.removeprefix("Bearer ").strip()
    try:
        idinfo = google_id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            GOOGLE_CLIENT_ID,
        )
    except Exception as exc:
        audit_log("auth_denied", severity="WARNING", reason="invalid_token", path=path)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired Google ID token: {exc}",
        ) from exc

    issuer = idinfo.get("iss")
    if issuer not in {"accounts.google.com", "https://accounts.google.com"}:
        audit_log("auth_denied", severity="WARNING", reason="invalid_issuer", path=path)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token issuer.",
        )

    if not idinfo.get("email_verified"):
        audit_log("auth_denied", severity="WARNING", reason="unverified_email", path=path)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Google account email is not verified.",
        )

    email = str(idinfo.get("email", "")).lower()
    if email not in ALLOWED_EMAILS:
        audit_log(
            "auth_denied",
            severity="WARNING",
            reason="email_not_allowlisted",
            attemptedEmail=email,
            path=path,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied for {email}. This research backend is locked to the owner account.",
        )

    audit_log("auth_success", severity="INFO", email=email, path=path)
    return {
        "email": email,
        "name": idinfo.get("name", email),
        "picture": idinfo.get("picture", ""),
    }


# ---------- Request Models ----------
class ResearchRequest(BaseModel):
    prompt: str = Field(..., min_length=4, max_length=600)
    monthId: str | None = Field(default=None)
    duration: str | None = Field(default="auto")
    autoSave: bool = Field(default=True)


# ---------- Routes ----------
@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "app": "nordic-atlas",
        "env": APP_ENV,
        "researchModel": RESEARCH_MODEL,
        "synthModel": SYNTH_MODEL,
        "githubAutoSave": is_github_sync_enabled(),
    }


@app.get("/api/me")
async def me(user: dict = Depends(verify_google_owner)) -> dict:
    return {
        "authenticated": True,
        "email": user["email"],
        "name": user["name"],
        "picture": user["picture"],
        "researchModel": RESEARCH_MODEL,
        "githubAutoSave": is_github_sync_enabled(),
    }


@app.post("/api/research/stream")
async def research_stream(
    req: ResearchRequest,
    user: dict = Depends(verify_google_owner),
) -> StreamingResponse:
    """Spawn 3 parallel Google-Search-grounded Gemini agents and stream live SSE progress."""
    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def emit(event: dict) -> None:
        await queue.put(event)

    async def worker() -> None:
        t0 = time.monotonic()
        prompt_clean = req.prompt.strip()
        audit_log(
            "research_started",
            email=user["email"],
            prompt=prompt_clean[:200],
            monthHint=req.monthId,
            durationHint=req.duration,
            researchModel=RESEARCH_MODEL,
            synthModel=SYNTH_MODEL,
        )
        try:
            await emit({
                "type": "status",
                "message": f"Authenticated as {user['email']} — spawning 3 parallel Gemini agents…",
            })
            month_id, adventure = await run_parallel_research(
                user_prompt=prompt_clean,
                month_hint=req.monthId if req.monthId and req.monthId != "auto" else None,
                duration_hint=req.duration,
                emit=emit,
            )

            github_result: dict = {"saved": False}
            if req.autoSave and is_github_sync_enabled():
                await emit({
                    "type": "agent_start",
                    "agent": "github_sync",
                    "label": "GitHub Auto-Save",
                    "message": "Committing trip to data/custom.json & data/adventures.json…",
                })
                github_result = await save_custom_adventure_to_github(
                    month_id=month_id,
                    adventure=adventure,
                    prompt=prompt_clean,
                )
                await emit({
                    "type": "agent_done",
                    "agent": "github_sync",
                    "label": "GitHub Auto-Save",
                    "message": f"Committed {github_result.get('commitSha', '')} to main (GitHub Pages rebuilding)",
                })

            elapsed_total = round(time.monotonic() - t0, 1)
            audit_log(
                "research_completed",
                email=user["email"],
                adventureId=adventure["id"],
                monthId=month_id,
                title=adventure["title"],
                baseTotalUsd=adventure.get("computedCosts", {}).get("baseTotalUsd"),
                elapsedSec=elapsed_total,
                githubSaved=github_result.get("saved", False),
                commitSha=github_result.get("commitSha"),
            )
            await emit({
                "type": "complete",
                "monthId": month_id,
                "adventure": adventure,
                "github": github_result,
            })
        except Exception as exc:
            audit_log(
                "research_failed",
                severity="ERROR",
                email=user["email"],
                error=str(exc),
                elapsedSec=round(time.monotonic() - t0, 1),
            )
            await emit({"type": "error", "message": str(exc)})
        finally:
            await queue.put(None)

    asyncio.create_task(worker())

    async def event_generator() -> AsyncIterator[str]:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.delete("/api/adventures/{adv_id}")
async def delete_adventure(
    adv_id: str,
    user: dict = Depends(verify_google_owner),
) -> dict:
    if not adv_id.startswith("custom-"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only custom on-demand researched adventures can be deleted via API.",
        )
    try:
        res = await delete_custom_adventure_from_github(adv_id)
        audit_log(
            "adventure_deleted",
            email=user["email"],
            adventureId=adv_id,
            deleted=res.get("deleted", False),
            commitSha=res.get("commitSha"),
        )
        return res
    except Exception as exc:
        audit_log("adventure_delete_failed", severity="ERROR", adventureId=adv_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
