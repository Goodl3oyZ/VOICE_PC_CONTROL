"""App flows (redesign step 1): every app is a short guided flow of stages the phone shows as wizard screens.

PC1 owns the definitions. The phone walks the stages; when it runs a flow, PC1 checks the answers against the
stage options and turns them into an ordinary command sentence that the shortcut parser already understands,
so policy, approvals and the audit trail stay exactly as for a typed command. Tiles for apps that need the
connectors of later build steps are listed as not available yet.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from voice_contracts.models import ToolCall
from voice_contracts.tools import NAME_PATTERN, TOOLS

from .knowledge import Knowledge

PC2View = Mapping[str, Any]  # PC2's latest status: found_projects, office_recent, steam_games
_NO_PC2: PC2View = {}


class FlowError(ValueError):
    pass


@dataclass(frozen=True)
class Option:
    value: str
    label: str
    hint: str = ""
    available: bool = True


@dataclass(frozen=True)
class Stage:
    id: str
    kind: str  # "choice" | "text"
    question: str
    options: tuple[Option, ...] = ()
    source: str = ""  # choice options filled from knowledge: "projects" | "apps"
    when: tuple[str, tuple[str, ...]] | None = None  # shown only if answers[stage] is one of these
    placeholder: str = ""
    remember: str = ""  # settings key: the last answer is the default next time ("Using YouTube · change")
    slug: bool = False  # text answer becomes a project name ("Todo App" -> "todo-app")


@dataclass(frozen=True)
class Control:
    label: str
    command: str = ""  # a sentence for the shortcut parser; "{project}" etc. are filled from the answers
    call: Callable[[dict[str, str]], ToolCall] | None = None  # or an exact call (wizard-only tools)
    when: tuple[str, tuple[str, ...]] | None = None  # shown only for these answers (e.g. Word only)


@dataclass(frozen=True)
class FollowUp:
    """A free-text box after the flow ran, e.g. dictation: every sentence becomes one exact call."""
    label: str
    placeholder: str
    tool: str
    arg: str
    when: tuple[str, tuple[str, ...]] | None = None


@dataclass(frozen=True)
class Flow:
    id: str
    title: str
    subtitle: str
    icon: str
    group: str
    stages: tuple[Stage, ...] = ()
    build: Callable[[dict[str, str]], str | ToolCall | None] | None = None
    controls: tuple[Control, ...] = ()
    pick_results: bool = False  # after a search, the phone lists the results to open
    available: bool = True
    coming: str = ""  # why a tile is not available yet
    triggers: tuple[str, ...] = field(default=())  # spoken names that open this flow
    followup: FollowUp | None = None


MEDIA_CONTROLS = (
    Control("Play / Pause", "Pause the music"), Control("Next", "Next song"), Control("Previous", "Previous song"),
    Control("Volume up", "Volume up 20%"), Control("Volume down", "Volume down 20%"), Control("Mute", "Mute"),
    Control("Skip ad", "Skip ad"),
)
_QUERY_MAX = 200


def _q(a: dict[str, str]) -> str:
    return a["query"]


def _youtube(a: dict[str, str]) -> str | None:
    if a["what"] == "controls":
        return None
    return f"play {_q(a)}" if a["what"] == "play" else f"search {_q(a)} on youtube"


def _code(a: dict[str, str]) -> str | ToolCall:
    if a["what"] == "new":
        return ToolCall(tool="create_project", arguments={"name": a["name"], "description": a["description"]},
                        rationale=f"Create a new project “{a['name']}”: {a['description']}")
    if a["project"].startswith("repo:"):  # found on PC2, not registered: approve once, then pick it again
        name = a["project"][5:]
        return ToolCall(tool="register_project", arguments={"name": name, "path": a["project_path"]},
                        rationale=f"Let the AI work on the project “{name}”")
    if a["what"] == "open":
        return f"open project {a['project']}"
    return f"in the {a['project']} project {a['request']}"


_SOON = "Arrives with the Chrome extension (build step 2)"
OFFICE_DOC = {"word": "document", "excel": "workbook", "powerpoint": "presentation"}


def _obs(a: dict[str, str]) -> ToolCall:
    if a["what"] == "start_stream":
        return ToolCall(tool="obs_start_stream", arguments={}, rationale="OBS: start streaming (goes public)")
    args = {"action": a["what"], "scene": a.get("scene", "")}
    return ToolCall(tool="obs_control", arguments=args, rationale=f"OBS: {a['what'].replace('_', ' ')}"
                    + (f" “{args['scene']}”" if args["scene"] else ""))


def _word_edit(action: str) -> Callable[[dict[str, str]], ToolCall]:
    return lambda a: ToolCall(tool="word_edit", arguments={"action": action})


def _office(a: dict[str, str]) -> ToolCall:
    app = a["app"]
    path = a.get(f"file_{app}_path", "")
    name = path.replace("/", "\\").split("\\")[-1] if path else f"a new {OFFICE_DOC[app]}"
    return ToolCall(tool="office_open", arguments={"app": app, "path": path},
                    rationale=f"Open {name} in {app.title() if app != 'powerpoint' else 'PowerPoint'}")

# ---- social (step 4): browsing is free; actions others can see go to the approval card with the exact text
_PAGE_LABELS = {"feed": ("Feed", ""), "foryou": ("For You", ""), "following": ("Following", ""),
                "search": ("Search", ""), "profile": ("Open a profile", ""), "messages": ("Messages", ""),
                "notifications": ("Notifications", ""), "reels": ("Reels", "")}
_ACT_LABELS = {"like": ("Like the open post", "You approve it on the phone"),
               "comment": ("Comment on the open post", "You approve the exact text"),
               "follow": ("Follow the open profile", "You approve it on the phone"),
               "post": ("Write a new post", "You approve the exact text"),
               "message": ("Send a message", "You approve the exact text")}
SOCIAL_FLOWS = [  # id, title, subtitle, group, pages, actions
    ("tiktok", "TikTok", "For You, search, like", "Watch & listen", ("foryou", "following", "search", "profile"),
     ("like", "comment", "follow")),
    ("facebook", "Facebook", "Feed, Messenger, post", "Social",
     ("feed", "search", "profile", "messages", "notifications"), ("like", "comment", "follow", "post", "message")),
    ("instagram", "Instagram", "Feed, Reels, DMs", "Social", ("feed", "reels", "search", "profile", "messages"),
     ("like", "comment", "follow", "message")),
    ("x", "X", "Timeline, search, post", "Social", ("feed", "search", "profile", "messages", "notifications"),
     ("like", "comment", "follow", "post", "message")),
]


def _social_build(platform: str) -> Callable[[dict[str, str]], ToolCall]:
    def build(a: dict[str, str]) -> ToolCall:
        what, name = a["what"], platform.title() if platform != "x" else "X"
        if what in _PAGE_LABELS:
            args = {"platform": platform, "page": what, "query": a.get("query") or a.get("account", "")}
            return ToolCall(tool="social_open", arguments=args, rationale=f"{name}: {_PAGE_LABELS[what][0].lower()}"
                            + (f" “{args['query']}”" if args["query"] else ""))
        args = {"platform": platform, "action": what, "text": a.get("text", ""), "to": a.get("to", "")}
        said = f": “{args['text']}”" if args["text"] else ""
        who = f" to @{args['to'].lstrip('@')}" if args["to"] else ""
        return ToolCall(tool="social_act", arguments=args, rationale=f"{name}: {what}{who}{said}")
    return build


def _social_flow(fid: str, title: str, subtitle: str, group: str, pages: tuple[str, ...],
                 actions: tuple[str, ...]) -> Flow:
    opts = tuple(Option(p, *_PAGE_LABELS[p]) for p in pages) + tuple(Option(a, *_ACT_LABELS[a]) for a in actions)
    return Flow(fid, title, subtitle, fid, group, stages=(
        Stage("what", "choice", "What do you want to do?", opts),
        Stage("query", "text", "Search for what?", when=("what", ("search",)), placeholder="cats, news…"),
        Stage("account", "text", "Which account?", when=("what", ("profile",)), placeholder="account name"),
        Stage("to", "text", "Send it to which account?", when=("what", ("message",)), placeholder="account name"),
        Stage("text", "text", "What should it say? You will approve the exact text.",
              when=("what", ("comment", "post", "message")), placeholder="Congrats!"),
    ), build=_social_build(fid), controls=(Control("What tabs are open?", "What tabs are open?"),
                                            Control("Close this tab", "Close this tab")), triggers=(fid,))
FLOWS: dict[str, Flow] = {f.id: f for f in [
    Flow("youtube", "YouTube", "Play, search, control", "youtube", "Watch & listen",
         stages=(
             Stage("what", "choice", "What do you want?", (
                 Option("play", "Play something now", "Plays the first match"),
                 Option("search", "Search and pick", "Shows the top 5 results"),
                 Option("controls", "Control what's playing", "Pause, next, volume"))),
             Stage("query", "text", "What should I look for?", when=("what", ("play", "search")),
                   placeholder="lofi hip hop, cooking pasta…"),
         ),
         build=_youtube, controls=MEDIA_CONTROLS, pick_results=True, triggers=("youtube",)),
    Flow("music", "Music", "Play by name", "music", "Watch & listen",
         stages=(
             Stage("app", "choice", "Which app for music?", (
                 Option("youtube", "YouTube"), Option("tiktok", "TikTok", _SOON, available=False)),
                 remember="last_music_app"),
             Stage("query", "text", "What should I play?", placeholder="lofi, relaxing piano…"),
         ),
         build=lambda a: f"play {_q(a)}", controls=MEDIA_CONTROLS, triggers=("music",)),
    Flow("search", "Search", "Google results on the phone", "search", "Web",
         stages=(Stage("query", "text", "What do you want to search for?", placeholder="cheap flights to Tokyo"),),
         build=lambda a: f"search for {_q(a)}", pick_results=True,
         controls=(Control("Close this tab", "Close this tab"), Control("What tabs are open?", "What tabs are open?")),
         triggers=("search", "google")),
    Flow("code", "Code", "Projects, changes, review", "code", "Work",
         stages=(
             Stage("what", "choice", "What for?", (
                 Option("change", "Change or add code", "The AI edits on an ai/… branch, then runs the tests"),
                 Option("open", "Just open it", "Opens the project in Cursor"),
                 Option("ask", "Ask about the code", "With Cursor's agent (needs Cursor login)", available=False),
                 Option("new", "Start a new project", "A new folder with git under your Projects folder"))),
             Stage("project", "choice", "Which project?", source="projects", remember="last_project",
                   when=("what", ("change", "open"))),
             Stage("request", "text", "What should change?", when=("what", ("change",)),
                   placeholder="add a function that…"),
             Stage("name", "text", "Name the new project", when=("what", ("new",)), placeholder="todo-app",
                   slug=True),
             Stage("description", "text", "Describe it in one sentence", when=("what", ("new",)),
                   placeholder="a todo app in React with dark mode"),
         ),
         build=_code,
         controls=(Control("Show the changes", "show the diff for {project}"),
                   Control("Run the tests", "run the tests in {project}"),
                   Control("Revert the AI changes", "revert the changes in {project}")),
         triggers=("cursor", "code", "coding", "projects")),
    Flow("apps", "Open an app", "Any app on the allowlist", "apps", "PC",
         stages=(Stage("app", "choice", "Which app?", source="apps"),),
         build=lambda a: f"open {a['app']}"),
    Flow("pc", "PC", "Status, screen, wake", "monitor", "PC",
         controls=(Control("What's running?", "Show status"), Control("Look at the screen", "What's on the screen?"),
                   Control("Wake up the PC", "Wake up the PC"), Control("Stop everything", "Stop"))),
    *[_social_flow(*f) for f in SOCIAL_FLOWS],
    Flow("obs", "OBS", "Record and stream", "obs", "Play",
         stages=(Stage("what", "choice", "What do you want to do?", (
             Option("start_recording", "Start recording"), Option("stop_recording", "Stop recording"),
             Option("start_stream", "Start streaming", "Goes public: you approve it on the phone"),
             Option("stop_streaming", "Stop streaming", "Always allowed, right away"),
             Option("set_scene", "Switch scene"), Option("status", "What's OBS doing?"))),
             Stage("scene", "text", "Which scene?", when=("what", ("set_scene",)), placeholder="Scene name")),
         build=_obs, triggers=("obs", "recording", "streaming"),
         controls=(Control("Start recording", call=lambda a: ToolCall(tool="obs_control",
                                                                      arguments={"action": "start_recording"})),
                   Control("Stop recording", call=lambda a: ToolCall(tool="obs_control",
                                                                     arguments={"action": "stop_recording"})),
                   Control("Stop streaming", call=lambda a: ToolCall(tool="obs_control",
                                                                     arguments={"action": "stop_streaming"})),
                   Control("Status", call=lambda a: ToolCall(tool="obs_control", arguments={"action": "status"})))),
    Flow("office", "Office", "Word, Excel, PowerPoint", "office", "Work",
         stages=(Stage("app", "choice", "Which app?", (Option("word", "Word"), Option("excel", "Excel"),
                                                        Option("powerpoint", "PowerPoint")), remember="last_office"),
                 *[Stage(f"file_{app}", "choice", "Which file?", source=f"office:{app}", when=("app", (app,)))
                   for app in OFFICE_DOC]),
         build=_office, triggers=("office", "word", "excel", "powerpoint"),
         followup=FollowUp("Dictate", "Say a sentence and it is typed into Word…", "word_type", "text",
                           when=("app", ("word",))),
         controls=(*[Control(label, call=_word_edit(act), when=("app", ("word",)))
                     for label, act in (("New paragraph", "new_paragraph"),
                                        ("Delete last sentence", "delete_last_sentence"),
                                        ("Read back last paragraph", "read_last_paragraph"), ("Undo", "undo"))],
                   Control("Save as a new copy", call=lambda a: ToolCall(tool="office_save_copy",
                                                                         arguments={"app": a["app"]})),
                   Control("Save (overwrite)", call=lambda a: ToolCall(tool="office_finish",
                                                                       arguments={"app": a["app"], "mode": "save"})),
                   Control("Close without saving", call=lambda a: ToolCall(
                       tool="office_finish", arguments={"app": a["app"], "mode": "close_discard"})))),
    Flow("steam", "Steam", "Launch your games", "steam", "Play",
         stages=(Stage("game", "choice", "Which game?", source="steam", remember="last_game"),),
         build=lambda a: ToolCall(tool="steam_launch", arguments={"appid": a["game"]},
                                  rationale="Start a Steam game"),
         triggers=("steam", "games")),
]}


def _list(pc2: PC2View, key: str, sub: str | None = None) -> list[dict[str, str]]:
    v: Any = pc2.get(key)
    if sub is not None:
        v = v.get(sub) if isinstance(v, dict) else None
    if not isinstance(v, list):
        return []
    return [x for x in v if isinstance(x, dict) and all(isinstance(y, str) for y in x.values())]


def _folder(path: str) -> str:
    parts = path.replace("/", "\\").split("\\")
    return "\\".join(parts[-3:-1]) if len(parts) > 2 else ""


def _options(stage: Stage, kb: Knowledge, pc2: PC2View = _NO_PC2) -> list[Option]:
    if stage.source == "projects":
        mine = [Option(p, str(v.get("display", p)) if isinstance(v, dict) else p) for p, v in kb.projects.items()]
        return mine + [Option(f"repo:{f['name']}", f.get("label") or f["name"],
                              "Found on the PC · you approve once, then pick it again")
                       for f in _list(pc2, "found_projects") if f.get("name") and f["name"] not in kb.projects]
    if stage.source.startswith("office:"):
        app = stage.source[7:]
        return [Option("new", f"New blank {OFFICE_DOC[app]}")] + [
            Option(f"file:{i}", f.get("name", "?"), _folder(f.get("path", "")))
            for i, f in enumerate(_list(pc2, "office_recent", app)[:8])]
    if stage.source == "steam":
        return [Option(g["appid"], g.get("name", g["appid"])) for g in _list(pc2, "steam_games")
                if g.get("appid", "").isdigit()][:20]
    if stage.source == "apps":
        return [Option(a, kb.display(a, "en")) for a in kb.apps]
    return list(stage.options)


def public_flows(kb: Knowledge, settings: Callable[[str], str | None],
                 pc2: PC2View = _NO_PC2) -> list[dict[str, Any]]:
    """What the phone draws: tiles, stages with their options, defaults remembered from last time."""
    out = []
    for f in FLOWS.values():
        stages = []
        for s in f.stages:
            opts = _options(s, kb, pc2)
            default = settings(f"flow.{s.remember}") if s.remember else None
            if default not in {o.value for o in opts if o.available}:
                default = None
            stages.append({"id": s.id, "kind": s.kind, "question": s.question, "placeholder": s.placeholder,
                           "when": {"stage": s.when[0], "values": list(s.when[1])} if s.when else None,
                           "default": default,
                           "options": [{"value": o.value, "label": o.label, "hint": o.hint,
                                        "available": o.available} for o in opts]})
        out.append({"id": f.id, "title": f.title, "subtitle": f.subtitle, "icon": f.icon, "group": f.group,
                    "available": f.available, "coming": f.coming, "pick_results": f.pick_results,
                    "stages": stages,
                    "controls": [{"label": c.label, "command": c.command or c.label, "when": _when(c.when)}
                                 for c in f.controls],
                    "followup": None if f.followup is None else {
                        "label": f.followup.label, "placeholder": f.followup.placeholder,
                        "when": _when(f.followup.when)}})
    return out


def _active(stage: Stage, answers: dict[str, str]) -> bool:
    return stage.when is None or answers.get(stage.when[0]) in stage.when[1]


def resolve(flow_id: str, answers: dict[str, str], kb: Knowledge,
            pc2: PC2View = _NO_PC2) -> tuple[str | ToolCall | None, dict[str, str]]:
    """Check the answers and build the command sentence. Returns (command or None, values to remember)."""
    f = FLOWS.get(flow_id)
    if f is None or not f.available:
        raise FlowError("unknown flow")
    clean: dict[str, str] = {}
    remember: dict[str, str] = {}
    for s in f.stages:
        if not _active(s, clean):
            continue
        v = " ".join(str(answers.get(s.id, "")).split())
        if s.kind == "choice":
            allowed = {o.value for o in _options(s, kb, pc2) if o.available}
            if v not in allowed:
                raise FlowError(f"choose one of the options for '{s.question}'")
            if v.startswith("repo:"):  # the path comes from PC2's own scan, never from the phone
                clean[f"{s.id}_path"] = next(f["path"] for f in _list(pc2, "found_projects") if f["name"] == v[5:])
            elif v.startswith("file:"):  # same for Office's recent files
                clean[f"{s.id}_path"] = _list(pc2, "office_recent", s.source[7:])[int(v[5:])]["path"]
            elif s.remember:
                remember[f"flow.{s.remember}"] = v
        else:
            if not v:
                raise FlowError(f"'{s.question}' needs an answer")
            v = v[:_QUERY_MAX]
            if s.slug:
                v = re.sub(r"[^a-z0-9_\-]+", "-", v.lower()).strip("-_")[:32]
                if not re.match(NAME_PATTERN, v) or v in kb.projects:
                    raise FlowError("pick a different project name (letters, digits and -)")
        clean[s.id] = v
    command = f.build(clean) if f.build else None
    if isinstance(command, ToolCall):  # check the exact call now, so the phone gets a clear message
        _check(command)
    return command, remember


def _check(call: ToolCall) -> ToolCall:
    try:
        TOOLS[call.tool].args.model_validate(call.arguments)
    except ValidationError as e:
        raise FlowError(str(e.errors()[0].get("msg", "invalid answer")).removeprefix("Value error, ")) from e
    return call


def _when(w: tuple[str, tuple[str, ...]] | None) -> dict[str, Any] | None:
    return {"stage": w[0], "values": list(w[1])} if w else None


def control_command(flow_id: str, index: int, answers: dict[str, str], kb: Knowledge,
                    pc2: PC2View = _NO_PC2) -> str | ToolCall:
    """A follow-up control ("Next", "Show the changes", "New paragraph"), filled from CHECKED answers only."""
    f = FLOWS.get(flow_id)
    if f is None or not f.available or not 0 <= index < len(f.controls):
        raise FlowError("unknown control")
    c = f.controls[index]
    if c.call is not None:
        checked = _checked(f, answers, kb, pc2)
        if c.when and checked.get(c.when[0]) not in c.when[1]:
            raise FlowError("that control does not apply here")
        call = _check(c.call(checked))
        if not call.rationale:  # the history shows this text: "Word: Close without saving", not "office_finish"
            call = call.model_copy(update={"rationale": f"{f.title}: {c.label}"})
        return call
    cmd = c.command
    for key in re.findall(r"\{(\w+)\}", cmd):
        stage = next((s for s in f.stages if s.id == key), None)
        if stage is None or answers.get(key) not in {o.value for o in _options(stage, kb, pc2) if o.available}:
            raise FlowError(f"missing {key}")
        cmd = cmd.replace("{" + key + "}", answers[key])
    return cmd


def _checked(f: Flow, answers: dict[str, str], kb: Knowledge, pc2: PC2View) -> dict[str, str]:
    """Only choice answers that are valid options (controls never take free text from the phone)."""
    out: dict[str, str] = {}
    for s in f.stages:
        if s.kind == "choice" and _active(s, out) and answers.get(s.id) in {o.value for o in _options(s, kb, pc2)}:
            out[s.id] = answers[s.id]
    return out


def followup_call(flow_id: str, text: str, answers: dict[str, str], kb: Knowledge,
                  pc2: PC2View = _NO_PC2) -> ToolCall:
    f = FLOWS.get(flow_id)
    if f is None or not f.available or f.followup is None:
        raise FlowError("this flow takes no follow-up text")
    fu = f.followup
    if fu.when and _checked(f, answers, kb, pc2).get(fu.when[0]) not in fu.when[1]:
        raise FlowError("dictation works in Word only")
    text = " ".join(text.split())[:2000]
    if not text:
        raise FlowError("say or type something")
    return _check(ToolCall(tool=fu.tool, arguments={fu.arg: text}, rationale=f"{fu.label}: “{text[:80]}”"))


_TRIGGER_RE = re.compile(r"^(?:(?:open|start|launch|show|go\s+to)\s+(?:the\s+|my\s+)?)?(?P<name>[a-z ]+?)"
                         r"(?:\s+(?:app|flow))?$", re.I)


def flow_trigger(normalized: str) -> str | None:
    """'YouTube', 'open Cursor', 'open the code app' -> that flow's wizard on the phone."""
    m = _TRIGGER_RE.match(" ".join(normalized.lower().strip(" .!?,").split()))
    if not m:
        return None
    name = m["name"].strip()
    return next((f.id for f in FLOWS.values() if f.available and name in f.triggers), None)
