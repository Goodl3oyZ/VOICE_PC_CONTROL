"""Social sites in the owner's own Chrome (app flows step 4).

social_open (risk 1): feed, search, a profile, messages. social_act (risk 3): like, comment, follow, post,
message: only with the owner's approval of the exact text (PC2 policy checks the approval hash), only from the
phone wizard (PC1 denies it to the planner), at most `social_limit_per_hour` per platform, never on a login
page. Page content is untrusted.
"""
from __future__ import annotations

from voice_contracts.models import ToolResult
from voice_contracts.tools import SocialActArgs, SocialOpenArgs

from ..browser import BrowserError
from . import ToolContext, register


def _social(ctx: ToolContext):  # type: ignore[no-untyped-def]
    b = ctx.browser
    if b is None or not hasattr(b, "social_act"):
        raise BrowserError("social sites need the Voice PC Chrome extension (browser_mode: extension)")
    return b


@register("social_open")
def social_open(args: SocialOpenArgs, ctx: ToolContext) -> ToolResult:
    try:
        data = _social(ctx).social_open(args.platform, args.page, args.query)
    except BrowserError as e:
        return ToolResult(ok=False, error=str(e))
    return ToolResult(ok=True, verified=True, untrusted=True, data=data)


@register("social_act")
def social_act(args: SocialActArgs, ctx: ToolContext) -> ToolResult:
    try:
        data = _social(ctx).social_act(args.platform, args.action, args.text, args.to)
    except BrowserError as e:
        return ToolResult(ok=False, error=str(e))
    if data.get("error"):
        return ToolResult(ok=False, error=str(data["error"])[:300], data=data)
    # verified = the page shows the result (button state changed / the text appears)
    return ToolResult(ok=True, verified=bool(data.get("ok")), untrusted=True, data=data)
