"""WhatsApp entry point with interactive menus for SME Cashflow Coach.

Requires Meta WhatsApp Business API credentials + GOOGLE_API_KEY.
For a local demo without Meta, use `desk.py` (no LLM) or `demo.py`.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import httpx
from agentkernel.adk import GoogleADKModule
from agentkernel.api import RESTAPI
from agentkernel.whatsapp import AgentWhatsAppRequestHandler
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from agent import AGENTS
from dedupe import RecentMessageIds
from menus import is_menu_trigger, main_menu_payload, prompt_for_menu_id, quick_reply_buttons_payload


def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key:
            os.environ[key] = value


def _require_env() -> None:
    required = [
        "GOOGLE_API_KEY",
        "AK_WHATSAPP__VERIFY_TOKEN",
        "AK_WHATSAPP__ACCESS_TOKEN",
        "AK_WHATSAPP__APP_SECRET",
        "AK_WHATSAPP__PHONE_NUMBER_ID",
    ]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        print(
            "Missing required environment variables:\n  "
            + "\n  ".join(missing)
            + "\n\nSee .env.example. Get a free Gemini key at https://aistudio.google.com/apikey",
            file=sys.stderr,
        )
        raise SystemExit(1)


class CashflowWhatsAppHandler(AgentWhatsAppRequestHandler):
    """Menus + fast webhook ACK + message-id dedupe to stop repeated prompt runs."""

    def __init__(self) -> None:
        super().__init__()
        self._seen_messages = RecentMessageIds()

    def get_router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/health")
        def health():
            return {"status": "ok"}

        @router.get("/whatsapp/webhook")
        async def verify_webhook(request: Request):
            return await self._verify_webhook(request)

        @router.post("/whatsapp/webhook")
        async def handle_webhook(request: Request, background_tasks: BackgroundTasks):
            # Read body once (signature + JSON). Reply 200 immediately so Meta does not retry.
            raw = await request.body()
            if self._app_secret:
                signature = request.headers.get("x-hub-signature-256", "")
                if not self._verify_signature(raw, signature):
                    self._log.warning("Invalid request signature")
                    raise HTTPException(status_code=403, detail="Invalid signature")
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                self._log.warning("Invalid WhatsApp webhook JSON")
                return {"status": "ok"}

            background_tasks.add_task(self._process_webhook_body, body)
            return {"status": "ok"}

        return router

    async def _process_webhook_body(self, body: dict) -> None:
        try:
            if body.get("object") != "whatsapp_business_account":
                return
            for entry in body.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    for message in value.get("messages", []) or []:
                        await self._handle_message(message, value)
                    for status in value.get("statuses", []) or []:
                        self._log.debug("Message status update: %s", status)
        except Exception:
            self._log.exception("Background WhatsApp processing failed")

    async def _send_payload(self, payload: dict) -> None:
        url = f"{self._base_url}/{self._phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {self._access_token}", "Content-Type": "application/json"}
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers, timeout=30.0)
            if response.is_error:
                self._log.error("Failed to send interactive message: %s", response.text)
            response.raise_for_status()

    async def _send_main_menu(self, to_number: str, reply_to_message_id: Optional[str] = None) -> None:
        payload = main_menu_payload(to_number)
        if reply_to_message_id:
            payload["context"] = {"message_id": reply_to_message_id}
        await self._send_payload(payload)

    async def _send_quick_buttons(self, to_number: str) -> None:
        await self._send_payload(quick_reply_buttons_payload(to_number))

    async def _handle_message(self, message: dict, value: dict):
        message_id = message.get("id")
        from_number = message.get("from")
        message_type = message.get("type")
        if not from_number or not message_id:
            return

        # Drop Meta retries / duplicate deliveries of the same inbound message.
        if self._seen_messages.seen_or_add(message_id):
            self._log.info("Skipping duplicate WhatsApp message id=%s", message_id)
            return

        text = None
        row_id = None
        if message_type == "text":
            text = (message.get("text") or {}).get("body", "").strip()
        elif message_type == "interactive":
            interactive = message.get("interactive") or {}
            if interactive.get("type") == "button_reply":
                reply = interactive.get("button_reply") or {}
                row_id = reply.get("id")
                text = reply.get("title")
            elif interactive.get("type") == "list_reply":
                reply = interactive.get("list_reply") or {}
                row_id = reply.get("id")
                text = reply.get("title")

        if text and is_menu_trigger(text):
            await self._send_main_menu(from_number, message_id)
            return

        mapped = prompt_for_menu_id(row_id or "")
        if mapped:
            modified = dict(message)
            modified["type"] = "text"
            modified["text"] = {"body": mapped}
            await super()._handle_message(modified, value)
            try:
                await self._send_quick_buttons(from_number)
            except Exception as exc:  # noqa: BLE001
                self._log.warning("Could not send quick buttons: %s", exc)
            return

        await super()._handle_message(message, value)


_load_dotenv()
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "FALSE")
_require_env()

GoogleADKModule(AGENTS)


if __name__ == "__main__":
    RESTAPI.run([CashflowWhatsAppHandler()])
