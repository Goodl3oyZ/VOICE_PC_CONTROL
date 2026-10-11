"""open_app / open_url (Phase 1, risk 1)."""
from __future__ import annotations

from voice_contracts.models import ToolResult
from voice_contracts.tools import OpenAppArgs, OpenUrlArgs, SearchWebArgs, host_allowed, search_url

from . import ToolContext, register


@register("open_app")
def open_app(args: OpenAppArgs, ctx: ToolContext) -> ToolResult:
    entry = ctx.cfg.apps.get(args.app)
    if entry is None:
        return ToolResult(ok=False, error="app not in allowlist")
    if ctx.launcher.is_running(entry.process):
        # Idempotent: don't open a second window just because the command was repeated (TC-F04).
        return ToolResult(ok=True, verified=True, data={"app": args.app, "already_running": True})
    if entry.argv:
        ctx.launcher.launch(entry.argv)
    elif entry.uri:
        ctx.launcher.open_uri(entry.uri)
    else:
        return ToolResult(ok=False, error="app has no launch method configured")
    seen = ctx.wait_until(lambda: ctx.launcher.is_running(entry.process), ctx.cfg.verify_timeout_s)
    if not seen:
        return ToolResult(ok=True, verified=False, data={"app": args.app},
                          error=f"สั่งเปิดแล้วแต่ไม่พบโปรเซส {entry.process}")
    return ToolResult(ok=True, verified=True, data={"app": args.app, "already_running": False})


@register("search_web")
def search_web(args: SearchWebArgs, ctx: ToolContext) -> ToolResult:
    # URL is built here from a fixed base + percent-encoded query: the model never supplies a raw URL.
    url = search_url(args.site, args.query)
    if ctx.cfg.browser_argv:
        ctx.launcher.launch([*ctx.cfg.browser_argv, url])
    else:
        ctx.launcher.open_uri(url)
    seen = ctx.wait_until(lambda: ctx.launcher.is_running(ctx.cfg.browser_process), ctx.cfg.verify_timeout_s)
    return ToolResult(ok=True, verified=seen, data={"site": args.site, "query": args.query, "url": url},
                      error=None if seen else "ไม่พบเบราว์เซอร์หลังสั่งเปิด")


@register("open_url")
def open_url(args: OpenUrlArgs, ctx: ToolContext) -> ToolResult:
    if not host_allowed(args.url, ctx.cfg.allowed_hosts):
        return ToolResult(ok=False, error="host not in allowlist")
    if ctx.cfg.browser_argv:
        ctx.launcher.launch([*ctx.cfg.browser_argv, args.url])
    else:
        ctx.launcher.open_uri(args.url)
    seen = ctx.wait_until(lambda: ctx.launcher.is_running(ctx.cfg.browser_process),
                          ctx.cfg.verify_timeout_s)
    return ToolResult(ok=True, verified=seen, data={"url": args.url},
                      error=None if seen else "ไม่พบเบราว์เซอร์หลังสั่งเปิด")
