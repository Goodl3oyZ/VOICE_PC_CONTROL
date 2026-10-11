"""Short Thai summaries built from the *verified* tool result, never from LLM guesses (US-205)."""
from __future__ import annotations

from typing import Any

from voice_contracts.models import ToolResult
from voice_contracts.tools import host_of

from .knowledge import Knowledge

DENY_REASONS_TH = {
    "unknown tool": "ไม่มีเครื่องมือนี้",
    "app not in allowlist": "แอปนี้ไม่อยู่ในรายการที่อนุญาต",
    "host not in allowlist": "เว็บนี้ไม่อยู่ในรายการที่อนุญาต",
    "kill switch on": "ระบบถูกหยุดฉุกเฉินอยู่ (kill switch)",
    "rate limit": "สั่งถี่เกินไป รอสักครู่",
    "forbidden by default": "คำสั่งนี้ถูกห้ามโดยค่าเริ่มต้น",
}


def deny_message(reason: str) -> str:
    if reason.startswith("bad args"):
        return "คำสั่งไม่ถูกต้องตามรูปแบบที่อนุญาต"
    return DENY_REASONS_TH.get(reason, reason)


def summarize(tool: str, args: dict[str, Any], result: ToolResult, kb: Knowledge) -> str:
    if not result.ok:
        return f"ทำไม่สำเร็จ: {result.error or 'ไม่ทราบสาเหตุ'}"
    if not result.verified:
        return "สั่งไปแล้วแต่ตรวจไม่พบผลลัพธ์ จึงถือว่ายังไม่สำเร็จ"
    if tool == "open_app":
        name = kb.display(args["app"])
        return f"{name} เปิดอยู่แล้ว" if result.data.get("already_running") else f"เปิด {name} แล้ว"
    if tool == "open_url":
        return f"เปิด {host_of(args['url'])} แล้ว"
    if tool == "get_status":
        running = result.data.get("running") or []
        apps = ", ".join(kb.display(a) for a in running) or "ไม่มี"
        ks = " · kill switch เปิดอยู่" if result.data.get("kill_switch") else ""
        return f"PC2 ออนไลน์ · แอปที่เปิดอยู่: {apps}{ks}"
    if tool == "stop_all":
        return "หยุดงานทั้งหมดแล้ว"
    return "เสร็จแล้ว"
