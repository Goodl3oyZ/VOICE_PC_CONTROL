"""User-facing messages in one place, per interface language (VPC_LANGUAGE = "en" | "th").

English-only mode exists because Whisper `small` on the 4 GB/CPU setup is far more accurate in English
than in Thai; commands in any other language are rejected with a clear message instead of being guessed.
"""
from __future__ import annotations

import re

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "only_english": "Only English or Thai is supported. Please say or type your command in English or Thai.",
        "confirm_expired": "Confirmation timed out",
        "not_approved": "Not approved by the user",
        "args_mismatch": "Parameters differ from the confirmation card, so nothing was run",
        "user_stopped": "Stopped by the user",
        "user_cancelled": "Cancelled by the user",
        "stale_job": "Left unfinished by a system restart, cancelled automatically",
        "cancelled": "Cancelled",
        "job_timeout": "Took too long (job timeout)",
        "audit_failed": "Could not write the audit log, so nothing was run (fail closed)",
        "internal_error": "Internal error: {name}",
        "stt_timeout": "Speech recognition took too long",
        "no_speech": "No speech detected. Try again or type the command.",
        "stt_confirm": 'I heard "{text}". Is that right? Say or tap "yes", or say it again.',
        "clarify_default": "Could you tell me a bit more?",
        "no_tool": "There is no tool that can do this",
        "llm_invalid": "The AI returned an invalid answer, so nothing was run",
        "loop_repeat": "The AI repeated the same action, stopped (loop guard)",
        "max_steps": "Too many steps (loop guard)",
        "breaker": "PC2 keeps failing; connection paused for a moment (circuit breaker)",
        "pc2_offline": "PC2 is offline, commands cannot run right now",
        "pc2_offline_wol": "PC2 is offline. If it is asleep, say “wake up the PC”",
        "wol_not_set": "Wake-on-LAN is not set up (VPC_PC2_MAC on PC1)",
        "pc2_unreachable": "Cannot reach PC2 ({reason})",
        "pc2_slow": "PC2 took too long to answer",
        "clarify_expired": "No answer in time, cancelled automatically",
    },
    "th": {
        "only_english": "รองรับเฉพาะภาษาอังกฤษหรือไทย กรุณาพูดหรือพิมพ์คำสั่งเป็นภาษาอังกฤษหรือไทย",
        "confirm_expired": "หมดเวลายืนยัน",
        "not_approved": "ผู้ใช้ไม่อนุมัติ",
        "args_mismatch": "พารามิเตอร์ไม่ตรงกับที่แสดงในการ์ดยืนยัน จึงไม่ทำงาน",
        "user_stopped": "ผู้ใช้กดหยุด",
        "user_cancelled": "ผู้ใช้ยกเลิกงานนี้",
        "stale_job": "งานค้างจากการรีสตาร์ทระบบ ยกเลิกอัตโนมัติ",
        "cancelled": "ยกเลิกแล้ว",
        "job_timeout": "หมดเวลาทำงาน (job timeout)",
        "audit_failed": "เขียน audit log ไม่ได้ จึงไม่ทำงานต่อ (fail closed)",
        "internal_error": "ข้อผิดพลาดภายใน: {name}",
        "stt_timeout": "ถอดเสียงช้าเกินกำหนด",
        "no_speech": "ไม่ได้ยินเสียงพูด ลองใหม่หรือพิมพ์แทน",
        "stt_confirm": 'ได้ยินว่า "{text}" ใช่ไหม? ตอบ "ใช่" หรือพิมพ์ข้อความที่ถูกต้อง',
        "clarify_default": "ช่วยบอกเพิ่มหน่อยครับ",
        "no_tool": "ไม่มีเครื่องมือที่ทำคำสั่งนี้ได้",
        "llm_invalid": "AI ตอบไม่ถูกรูปแบบ จึงไม่ได้ทำอะไร",
        "loop_repeat": "AI เรียกคำสั่งเดิมซ้ำ จึงหยุดไว้ก่อน (loop guard)",
        "max_steps": "เกินจำนวนขั้นสูงสุดที่กำหนด (loop guard)",
        "breaker": "PC2 ล้มเหลวต่อเนื่อง พักการเชื่อมต่อชั่วคราว (circuit breaker)",
        "pc2_offline": "PC2 ออฟไลน์อยู่ สั่งงานไม่ได้ตอนนี้",
        "pc2_offline_wol": "PC2 ออฟไลน์อยู่ ถ้าหลับอยู่ให้พูดว่า “wake up the PC”",
        "wol_not_set": "ยังไม่ได้ตั้งค่า Wake-on-LAN (VPC_PC2_MAC บน PC1)",
        "pc2_unreachable": "ติดต่อ PC2 ไม่ได้ ({reason})",
        "pc2_slow": "PC2 ตอบช้าเกินกำหนด",
        "clarify_expired": "ไม่ได้รับคำตอบในเวลาที่กำหนด ยกเลิกอัตโนมัติ",
    },
}

YES_WORDS = {"ใช่", "ใช่ครับ", "ใช่ค่ะ", "ถูก", "ถูกต้อง", "โอเค", "ตกลง",
             "ok", "okay", "yes", "yeah", "yep", "correct", "right", "sure"}

_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)


def is_english(text: str, min_ratio: float = 0.85) -> bool:
    """True when (almost) all letters are ASCII Latin. Digits, punctuation and spaces are ignored."""
    letters = _LETTER.findall(text)
    if not letters:
        return False
    ascii_letters = sum(1 for ch in letters if ch.isascii())
    return ascii_letters / len(letters) >= min_ratio


def is_english_or_thai(text: str, min_ratio: float = 0.85) -> bool:
    """English, Thai, or both mixed ("play ลานดอกไม้"): other scripts are still refused."""
    letters = _LETTER.findall(text)
    if not letters:
        return False
    ok = sum(1 for ch in letters if ch.isascii() or "\u0e00" <= ch <= "\u0e7f")
    return ok / len(letters) >= min_ratio


class Messages:
    def __init__(self, language: str = "th"):
        self.language = language if language in MESSAGES else "th"

    def __call__(self, key: str, **kw: object) -> str:
        return MESSAGES[self.language][key].format(**kw)
