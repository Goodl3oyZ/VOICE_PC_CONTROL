"""Short summaries built from the *verified* tool result, never from LLM guesses (US-205). Thai or English."""
from __future__ import annotations

from typing import Any

from voice_contracts.models import ToolResult
from voice_contracts.tools import host_of

from .knowledge import Knowledge

DENY_REASONS = {
    "th": {
        "unknown tool": "ไม่มีเครื่องมือนี้",
        "app not in allowlist": "แอปนี้ไม่อยู่ในรายการที่อนุญาต",
        "host not in allowlist": "เว็บนี้ไม่อยู่ในรายการที่อนุญาต",
        "kill switch on": "ระบบถูกหยุดฉุกเฉินอยู่ (kill switch)",
        "rate limit": "สั่งถี่เกินไป รอสักครู่",
        "forbidden by default": "คำสั่งนี้ถูกห้ามโดยค่าเริ่มต้น",
        "bad args": "คำสั่งไม่ถูกต้องตามรูปแบบที่อนุญาต",
    },
    "en": {
        "unknown tool": "There is no such tool",
        "app not in allowlist": "This app is not on the allowed list",
        "host not in allowlist": "This website is not on the allowed list",
        "kill switch on": "The emergency kill switch is on",
        "rate limit": "Too many commands, please wait a moment",
        "forbidden by default": "This action is forbidden by default",
        "bad args": "The command is not in an allowed format",
    },
}

TEXT = {
    "th": {
        "failed": "ทำไม่สำเร็จ: {error}", "unknown": "ไม่ทราบสาเหตุ",
        "unverified": "สั่งไปแล้วแต่ตรวจไม่พบผลลัพธ์ จึงถือว่ายังไม่สำเร็จ",
        "already_open": "{name} เปิดอยู่แล้ว", "opened": "เปิด {name} แล้ว",
        "status": "PC2 ออนไลน์ · แอปที่เปิดอยู่: {apps}{ks}", "none": "ไม่มี", "ks": " · kill switch เปิดอยู่",
        "stopped": "หยุดงานทั้งหมดแล้ว", "searched": "ค้นหา “{query}” บน {where} แล้ว",
        "play_pause": "สั่งเล่น/หยุดเพลงชั่วคราวแล้ว", "next": "ข้ามไปเพลงถัดไปแล้ว",
        "previous": "ย้อนกลับไปเพลงก่อนหน้าแล้ว", "volume_up": "เพิ่มเสียงประมาณ {pct}% แล้ว",
        "volume_down": "ลดเสียงประมาณ {pct}% แล้ว", "mute": "สลับปิด/เปิดเสียงแล้ว",
        "media": "ส่งคำสั่งควบคุมเพลงแล้ว", "done": "เสร็จแล้ว",
    },
    "en": {
        "failed": "Failed: {error}", "unknown": "unknown reason",
        "unverified": "Sent, but the result could not be verified, so it counts as not done",
        "already_open": "{name} is already open", "opened": "Opened {name}",
        "status": "PC2 online · running: {apps}{ks}", "none": "nothing", "ks": " · kill switch ON",
        "stopped": "Stopped everything", "searched": "Searched {where} for “{query}”",
        "play_pause": "Toggled play/pause", "next": "Skipped to the next track",
        "previous": "Went back to the previous track", "volume_up": "Volume up about {pct}%",
        "volume_down": "Volume down about {pct}%", "mute": "Toggled mute",
        "media": "Sent the media command", "done": "Done",
    },
}


def deny_message(reason: str, language: str = "th") -> str:
    table = DENY_REASONS.get(language, DENY_REASONS["th"])
    if reason.startswith("bad args"):
        return table["bad args"]
    return table.get(reason, reason)


def summarize(tool: str, args: dict[str, Any], result: ToolResult, kb: Knowledge, language: str = "th") -> str:
    t = TEXT.get(language, TEXT["th"])
    if not result.ok:
        return t["failed"].format(error=result.error or t["unknown"])
    if not result.verified:
        return t["unverified"]
    if tool == "open_app":
        name = kb.display(args["app"], language)
        return (t["already_open"] if result.data.get("already_running") else t["opened"]).format(name=name)
    if tool == "open_url":
        return t["opened"].format(name=host_of(args["url"]))
    if tool == "get_status":
        running = result.data.get("running") or []
        apps = ", ".join(kb.display(a, language) for a in running) or t["none"]
        return t["status"].format(apps=apps, ks=t["ks"] if result.data.get("kill_switch") else "")
    if tool == "stop_all":
        return t["stopped"]
    if tool == "search_web":
        where = "YouTube" if args.get("site") == "youtube" else "Google"
        return t["searched"].format(query=args["query"], where=where)
    if tool == "media_control":
        steps = int(result.data.get("steps") or args.get("steps") or 1)
        action = args.get("action", "")
        return t.get(action, t["media"]).format(pct=steps * 2)
    return t["done"]
