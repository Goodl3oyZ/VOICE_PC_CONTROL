"""Word, Excel and PowerPoint through Office's own COM automation (app flows step 5).

Text goes into the document through Word's object model, not simulated typing, so it lands in the right
document even when another window is in front. Only files from Office's own recent list can be opened.
Saving a COPY is free (the original stays untouched); saving over the file or closing without saving needs
approval (office_finish, risk 3).
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from voice_contracts.models import ToolResult
from voice_contracts.tools import OfficeAppArgs, OfficeFinishArgs, OfficeOpenArgs, WordEditArgs, WordTypeArgs

from . import ToolContext, register

PROGID = {"word": "Word.Application", "excel": "Excel.Application", "powerpoint": "PowerPoint.Application"}
REG_APP = {"word": "Word", "excel": "Excel", "powerpoint": "PowerPoint"}
EXT = {"word": (".docx", ".doc", ".docm", ".rtf", ".txt"), "excel": (".xlsx", ".xls", ".xlsm", ".csv"),
       "powerpoint": (".pptx", ".ppt", ".pptm")}
_MRU_ITEM = re.compile(r"\*(?P<path>[A-Za-z]:\\[^*]+)$")
_cache: dict[str, Any] = {"at": 0.0, "files": {}}


class OfficeError(Exception):
    pass


LICENSE_CODES = {0x80048240}  # PowerPoint's bare "invalid request" once it drops to reduced-functionality mode


def com_message(app: str, e: Exception) -> str:
    """Office's COM error in plain words. An expired Office license lets the apps open but blocks creating
    and changing files a few seconds after start (Excel says so; PowerPoint only returns 0x80048240)."""
    detail = e.args[2] if len(e.args) > 2 and isinstance(e.args[2], tuple) else ()
    text = str(detail[2] if len(detail) > 2 and detail[2] else e)
    code = (detail[5] & 0xFFFFFFFF) if len(detail) > 5 and isinstance(detail[5], int) else None
    if "license" in text.lower() or code in LICENSE_CODES:
        return (f"Office's license on this PC has expired, so {REG_APP.get(app, app.title())} can't create or "
                "change files (it can only show them). Activate Office on the PC to use this.")
    return text[:200]


def recent_files(limit: int = 8) -> dict[str, list[dict[str, str]]]:
    """Office's own recent-files lists (registry), newest first; only files that still exist."""
    if time.time() - _cache["at"] < 60:
        return dict(_cache["files"])
    out: dict[str, list[dict[str, str]]] = {a: [] for a in REG_APP}
    try:
        import winreg
    except ImportError:  # not Windows (CI)
        return out
    for app, reg in REG_APP.items():
        base = rf"Software\Microsoft\Office\16.0\{reg}\User MRU"
        items: list[tuple[str, str]] = []
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as root:
                for i in range(winreg.QueryInfoKey(root)[0]):
                    sub = winreg.EnumKey(root, i)
                    try:
                        with winreg.OpenKey(root, rf"{sub}\File MRU") as k:
                            for j in range(winreg.QueryInfoKey(k)[1]):
                                name, value, _ = winreg.EnumValue(k, j)
                                if name.startswith("Item ") and isinstance(value, str):
                                    items.append((name, value))
                    except OSError:
                        continue
        except OSError:
            continue
        items.sort(key=lambda nv: int(nv[0].split()[1]) if nv[0].split()[1].isdigit() else 999)
        for _, v in items:
            m = _MRU_ITEM.search(v)
            if m and Path(m["path"]).suffix.lower() in EXT[app] and Path(m["path"]).is_file():
                p = m["path"]
                if all(f["path"] != p for f in out[app]):
                    out[app].append({"name": Path(p).name, "path": p})
            if len(out[app]) >= limit:
                break
    _cache.update(at=time.time(), files=out)
    return out


def _com(app: str, start: bool = True) -> Any:
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    try:
        return win32com.client.GetActiveObject(PROGID[app])
    except Exception as e:  # noqa: BLE001 — not running
        if not start:
            raise OfficeError(f"{app.title()} is not open") from e
        return win32com.client.Dispatch(PROGID[app])


def _doc(app: str) -> Any:
    o = _com(app, start=False)
    attr = {"word": "ActiveDocument", "excel": "ActiveWorkbook", "powerpoint": "ActivePresentation"}[app]
    try:
        return o, getattr(o, attr)
    except Exception as e:  # noqa: BLE001
        raise OfficeError(f"no {app.title()} file is open") from e


@register("office_open")
def office_open(args: OfficeOpenArgs, ctx: ToolContext) -> ToolResult:
    if args.path and args.path not in {f["path"] for f in recent_files()[args.app]}:
        return ToolResult(ok=False, error="only files from Office's recent list can be opened")
    try:
        o = _com(args.app)
        o.Visible = True
        if args.app == "word":
            d = o.Documents.Open(args.path) if args.path else o.Documents.Add()
            name = d.Name
        elif args.app == "excel":
            d = o.Workbooks.Open(args.path) if args.path else o.Workbooks.Add()
            name = d.Name
        else:
            d = o.Presentations.Open(args.path) if args.path else o.Presentations.Add()
            if not args.path:
                d.Slides.Add(1, 1)  # ppLayoutTitle
            name = d.Name
        try:
            o.Activate() if args.app != "powerpoint" else d.Windows(1).Activate()
        except Exception:  # noqa: BLE001, S110 — bringing the window forward is best effort
            pass
    except OfficeError as e:
        return ToolResult(ok=False, error=str(e))
    except Exception as e:  # noqa: BLE001 — COM errors carry Office's own message
        return ToolResult(ok=False, error=f"{REG_APP[args.app]} could not open it: {com_message(args.app, e)}")
    return ToolResult(ok=True, verified=True, data={"app": args.app, "file": name, "new": not args.path})


@register("word_type")
def word_type(args: WordTypeArgs, ctx: ToolContext) -> ToolResult:
    try:
        o, d = _doc("word")
        before = d.Content.End
        text = args.text.strip()
        sel = o.Selection
        prev = d.Range(max(0, sel.Start - 1), sel.Start).Text if sel.Start > 0 else ""
        if prev and not prev.isspace():
            text = " " + text  # dictated sentences follow each other with a space
        sel.TypeText(text)
        grew = d.Content.End - before
    except OfficeError as e:
        return ToolResult(ok=False, error=str(e))
    except Exception as e:  # noqa: BLE001
        return ToolResult(ok=False, error=f"Word: {com_message('word', e)}")
    return ToolResult(ok=True, verified=grew >= len(args.text.strip()), data={"typed": len(args.text), "file": d.Name})


@register("word_edit")
def word_edit(args: WordEditArgs, ctx: ToolContext) -> ToolResult:
    try:
        o, d = _doc("word")
        sel = o.Selection
        data: dict[str, Any] = {"action": args.action, "file": d.Name}
        if args.action == "new_paragraph":
            sel.TypeParagraph()
        elif args.action == "undo":
            d.Undo(1)
        elif args.action == "delete_last_sentence":
            n = d.Sentences.Count
            if n == 0 or not d.Sentences(n).Text.strip():
                return ToolResult(ok=False, error="there is no sentence to delete")
            data["deleted"] = d.Sentences(n).Text.strip()[:200]
            d.Sentences(n).Delete()
        else:  # read_last_paragraph
            paras = [d.Paragraphs(i).Range.Text.strip() for i in range(d.Paragraphs.Count, 0, -1)]
            data["text"] = next((t for t in paras if t), "")[:1000]
    except OfficeError as e:
        return ToolResult(ok=False, error=str(e))
    except Exception as e:  # noqa: BLE001
        return ToolResult(ok=False, error=f"Word: {com_message('word', e)}")
    return ToolResult(ok=True, verified=True, data=data)


def _copy_path(path: str) -> Path:
    p = Path(path)
    for i in range(1, 100):
        cand = p.with_name(f"{p.stem} (voice copy{'' if i == 1 else ' ' + str(i)}){p.suffix}")
        if not cand.exists():
            return cand
    raise OfficeError("too many copies already")


@register("office_save_copy")
def office_save_copy(args: OfficeAppArgs, ctx: ToolContext) -> ToolResult:
    try:
        _, d = _doc(args.app)
        full = d.FullName
        if not Path(full).parent.exists() or not Path(full).suffix:  # never saved: put it in Documents
            full = str(Path.home() / "Documents" / (d.Name + {"word": ".docx", "excel": ".xlsx",
                                                               "powerpoint": ".pptx"}[args.app]))
        target = _copy_path(full)
        d.SaveCopyAs(str(target)) if args.app != "word" else d.SaveAs2(str(target))
    except OfficeError as e:
        return ToolResult(ok=False, error=str(e))
    except Exception as e:  # noqa: BLE001
        return ToolResult(ok=False, error=f"{REG_APP[args.app]}: {com_message(args.app, e)}")
    return ToolResult(ok=True, verified=target.exists(), data={"app": args.app, "saved_as": str(target)})


@register("office_finish")
def office_finish(args: OfficeFinishArgs, ctx: ToolContext) -> ToolResult:
    try:
        _, d = _doc(args.app)
        name = d.Name
        if args.mode == "save":
            d.Save()
            ok = bool(d.Saved)
        else:
            d.Close(False) if args.app != "powerpoint" else d.Close()  # False = do not save changes
            ok = True
    except OfficeError as e:
        return ToolResult(ok=False, error=str(e))
    except Exception as e:  # noqa: BLE001
        return ToolResult(ok=False, error=f"{REG_APP[args.app]}: {com_message(args.app, e)}")
    return ToolResult(ok=True, verified=ok, data={"app": args.app, "mode": args.mode, "file": name})
