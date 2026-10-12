"""Phase 2 browser tools on the agent browser. Everything read from web pages is UNTRUSTED (taint, FR-09):
PC1 marks the job tainted, so any later risk >= 2 action needs the user's confirmation (doc §20.5)."""
from __future__ import annotations

from voice_contracts.models import ToolResult
from voice_contracts.tools import BrowserTabsArgs, NoArgs, OpenResultArgs, WebSearchArgs, YoutubePlayArgs

from ..browser import BrowserError, CaptchaDetected
from . import ToolContext, register

CAPTCHA_MSG = "CAPTCHA detected — stopped. Please solve it yourself on PC2 if you want to continue."


def _guard(fn):  # type: ignore[no-untyped-def]
    def wrapper(args, ctx: ToolContext) -> ToolResult:  # type: ignore[no-untyped-def]
        if ctx.browser is None:
            return ToolResult(ok=False, error="agent browser not available")
        try:
            return fn(args, ctx)
        except CaptchaDetected as e:  # US-305: stop and tell the user, never try to bypass
            return ToolResult(ok=False, error=CAPTCHA_MSG, data={"captcha": True, "url": str(e)[:200]})
        except BrowserError as e:
            return ToolResult(ok=False, error=str(e))
    wrapper.__name__ = fn.__name__
    return wrapper


@register("web_search")
@_guard
def web_search(args: WebSearchArgs, ctx: ToolContext) -> ToolResult:
    results = ctx.browser.search(args.query, args.max_results, args.site)
    # verified = the search ran and the results page was parsed (zero results is a valid outcome)
    return ToolResult(ok=True, verified=True, untrusted=True, data={"query": args.query, "site": args.site,
                                                                       "results": results})


@register("open_result")
@_guard
def open_result(args: OpenResultArgs, ctx: ToolContext) -> ToolResult:
    page = ctx.browser.open_result(args.index)
    return ToolResult(ok=True, verified=bool(page.get("url")), untrusted=True, data={"index": args.index, **page})


@register("youtube_play")
@_guard
def youtube_play(args: YoutubePlayArgs, ctx: ToolContext) -> ToolResult:
    r = ctx.browser.youtube_play(args.query)
    playing = bool(r.get("playing"))
    return ToolResult(ok=True, verified=playing, untrusted=True, data={"query": args.query, **r},
                      error=None if playing else "the video opened but is not playing")


@register("browser_tabs")
@_guard
def browser_tabs(args: BrowserTabsArgs, ctx: ToolContext) -> ToolResult:
    r = ctx.browser.tabs(args.action)
    return ToolResult(ok=True, verified=True, untrusted=True, data={"action": args.action, **r})


@register("youtube_skip_ad")
@_guard
def youtube_skip_ad(args: NoArgs, ctx: ToolContext) -> ToolResult:
    if not hasattr(ctx.browser, "youtube_skip_ad"):
        return ToolResult(ok=False, error="skipping ads needs the Voice PC Chrome extension")
    d = ctx.browser.youtube_skip_ad()
    # verified: the extension reported the ad's real state (skipped / nothing to skip / YouTube offers no Skip)
    return ToolResult(ok=True, verified=True, data=d)
