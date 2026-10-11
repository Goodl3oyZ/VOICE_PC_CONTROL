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
        "results": "ผลค้นหา “{query}” ({where}): {items}. พูด “open result 2” เพื่อเปิด", "no_results": "ไม่พบผลลัพธ์",
        "opened_result": "เปิดผลลัพธ์ที่ {index}: {title}", "playing": "กำลังเล่น “{title}” บน YouTube",
        "tabs": "เปิดอยู่ {n} แท็บ: {titles}", "tab_switched": "สลับแท็บแล้ว: {title}",
        "tab_closed": "ปิดแท็บแล้ว (เหลือ {n})", "captcha": "เจอ CAPTCHA จึงหยุดไว้ กรุณาทำเองบน PC2",
        "opened_project": "เปิดโปรเจกต์ {project} ใน {ide} แล้ว", "files": "{project} มี {n} รายการ: {items}",
        "read": "อ่าน {path} แล้ว ({lines} บรรทัด)", "matches": "พบ {n} จุดที่ตรงกับ “{query}”: {items}",
        "no_matches": "ไม่พบ “{query}”", "git_status": "{project} อยู่บน {branch}; แก้ไข {n} ไฟล์",
        "edited": "แก้ {path} บนกิ่ง {branch} แล้ว ({stat})", "created": "สร้าง {path} บนกิ่ง {branch} แล้ว",
        "tests_passed": "เทสต์ผ่านใน {project} ({secs} วินาที)",
        "tests_failed": "เทสต์ไม่ผ่านใน {project} (exit {code}): {last}",
        "diff": "แก้ {n} ไฟล์บน {branch} เทียบกับ {base}: {files} ({stat})",
        "no_diff": "ไม่มีการแก้ไขจาก AI ใน {project}", "reverted": "ย้อนกลับแล้ว: กลับไป {base} ลบกิ่ง {branch}",
        "nothing_to_revert": "ไม่มีอะไรให้ย้อนใน {project}",
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
        "results": "Results for “{query}” ({where}): {items}. Say “open result 2” to open one",
        "no_results": "No results found",
        "opened_result": "Opened result {index}: {title}", "playing": "Playing “{title}” on YouTube",
        "tabs": "{n} tab(s) open: {titles}", "tab_switched": "Switched to: {title}",
        "tab_closed": "Closed the tab ({n} left)",
        "captcha": "CAPTCHA detected, stopped. Please solve it yourself on PC2",
        "opened_project": "Opened project {project} in {ide}", "files": "{n} item(s) in {project}: {items}",
        "read": "Read {path} ({lines} lines)", "matches": "{n} match(es) for “{query}”: {items}",
        "no_matches": "No matches for “{query}”", "git_status": "{project} is on {branch}; {n} changed file(s)",
        "edited": "Edited {path} on branch {branch} ({stat})", "created": "Created {path} on branch {branch}",
        "tests_passed": "Tests PASSED in {project} ({secs}s)",
        "tests_failed": "Tests FAILED in {project} (exit {code}): {last}",
        "diff": "{n} file(s) changed on {branch} vs {base}: {files} ({stat})",
        "no_diff": "No AI changes in {project}", "reverted": "Reverted: back on {base}, branch {branch} deleted",
        "nothing_to_revert": "Nothing to revert in {project}",
    },
}


def deny_message(reason: str, language: str = "th") -> str:
    table = DENY_REASONS.get(language, DENY_REASONS["th"])
    if reason.startswith("bad args"):
        return table["bad args"]
    return table.get(reason, reason)


def summarize(tool: str, args: dict[str, Any], result: ToolResult, kb: Knowledge, language: str = "th") -> str:
    t = TEXT.get(language, TEXT["th"])
    if not result.ok and result.data.get("captcha"):
        return t["captcha"]
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
    if tool == "web_search":
        results = result.data.get("results") or []
        if not results:
            return t["no_results"]
        items = " · ".join(f"{i}) {r.get('title', '')[:70]} — {r.get('host', '')}"
                           for i, r in enumerate(results[:3], 1))
        where = "YouTube" if args.get("site") == "youtube" else "Bing"
        return t["results"].format(query=args["query"], items=items, where=where)
    if tool == "open_result":
        return t["opened_result"].format(index=args["index"], title=(result.data.get("title") or "")[:90])
    if tool == "youtube_play":
        return t["playing"].format(title=(result.data.get("title") or args["query"])[:90])
    if tool == "browser_tabs":
        tabs = result.data.get("tabs") or []
        if args.get("action") == "close":
            return t["tab_closed"].format(n=len(tabs))
        if args.get("action") in ("next", "previous"):
            return t["tab_switched"].format(title=(tabs[-1]["title"] if tabs else ""))
        titles = " · ".join((tb.get("title") or tb.get("host") or "New tab")[:40] for tb in tabs[:6])
        return t["tabs"].format(n=len(tabs), titles=titles)
    d = result.data
    if tool == "wake_pc":
        if d.get("already"):
            return "PC2 is already awake"
        if d.get("online"):
            return f"PC2 is awake (took {d.get('secs')} s)"
        return ("Wake signal sent, but PC2 did not come online (it may be powered off, or Wake-on-LAN is off "
                "in its settings)")
    if tool == "look_at_screen":
        return str(d.get("description") or t["done"])
    if tool == "open_project":
        return t["opened_project"].format(project=args["project"], ide=d.get("ide", "the IDE"))
    if tool == "list_files":
        files = d.get("files") or []
        return t["files"].format(n=len(files), project=args["project"], items=", ".join(files[:8]))
    if tool == "read_file":
        return t["read"].format(path=args["path"], lines=d.get("lines", "?"))
    if tool == "search_code":
        m = d.get("matches") or []
        if not m:
            return t["no_matches"].format(query=args["query"])
        return t["matches"].format(n=len(m), query=args["query"],
                                   items=" · ".join(f"{x['file']}:{x['line']}" for x in m[:5]))
    if tool == "git_status":
        return t["git_status"].format(project=args["project"], branch=d.get("branch"),
                                      n=len(d.get("changed") or []))
    if tool == "edit_file":
        key = "created" if d.get("created") else "edited"
        return t[key].format(path=args["path"], branch=d.get("branch"), stat=d.get("stat", ""))
    if tool == "run_tests":
        if d.get("passed"):
            return t["tests_passed"].format(project=args["project"], secs=d.get("duration_s"))
        tail = [ln for ln in (d.get("output_tail") or "").splitlines() if ln.strip()]
        return t["tests_failed"].format(project=args["project"], code=d.get("exit_code"),
                                        last=(tail[-1] if tail else "")[:160])
    if tool == "git_diff":
        if not d.get("files"):
            return t["no_diff"].format(project=args["project"])
        return t["diff"].format(n=len(d["files"]), branch=d.get("branch"), base=d.get("base"),
                                files=", ".join(d["files"][:6]), stat=d.get("stat", ""))
    if tool == "revert_changes":
        if not d.get("reverted"):
            return t["nothing_to_revert"].format(project=args["project"])
        return t["reverted"].format(base=d.get("base"), branch=d.get("branch_deleted"))
    return t["done"]


def coding_report(job: Any, llm_message: str, language: str = "en") -> str:
    """Final report of a multi-step coding job, built from the verified step results — the test verdict comes
    from run_tests, never from the model's own claim (LLM09 misinformation)."""
    steps = job.steps
    project = next((s["arguments"].get("project") for s in steps if s["arguments"].get("project")), "the project")
    edits = [s for s in steps if s["tool"] == "edit_file" and s["result"].get("ok") and s["result"].get("verified")]
    branch = next((s["result"]["data"].get("branch") for s in reversed(edits)), None)
    tests = [s for s in steps if s["tool"] == "run_tests" and s["result"].get("ok")]
    passed = bool(tests) and bool(tests[-1]["result"]["data"].get("passed"))
    files = sorted({s["arguments"].get("path") for s in edits})
    if language == "th":
        verdict = "เทสต์ผ่าน" if passed else ("เทสต์ไม่ผ่าน" if tests else "ยังไม่ได้รันเทสต์")
        where = f"แก้ {len(edits)} ครั้งบนกิ่ง {branch} ({', '.join(files)})" if edits else "ไม่ได้แก้ไฟล์"
        return (f"{llm_message.strip() or 'จบงานโค้ด'} — {where}; {verdict}. "
                f"พูด “show the diff for {project}” หรือ “revert the changes in {project}”")
    verdict = "tests PASSED" if passed else ("tests FAILED" if tests else "tests not run")
    where = f"{len(edits)} edit(s) on branch {branch} ({', '.join(files)})" if edits else "no files changed"
    head = llm_message.strip().rstrip(".") or "Coding task finished"
    tried_edit = any(s["tool"] == "edit_file" for s in steps)
    if (tests and not passed) or (tried_edit and not edits):
        head = "Not finished — " + head
    if tried_edit and not edits:
        where = "no change could be applied"
    return (f"{head}. {where}; {verdict}. "
            f"Say “show the diff for {project}” or “revert the changes in {project}”.")
