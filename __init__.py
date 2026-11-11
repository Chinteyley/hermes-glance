"""Glance: Hermes looks at the running app before it calls a UI change done."""

from __future__ import annotations

from pathlib import Path


def register(ctx):
    from . import cli, hooks, schemas, tools

    def device() -> str:
        return str(ctx.get_config("device", default="") or "")

    ctx.register_tool(
        name="glance_check", toolset="glance", schema=schemas.GLANCE_CHECK,
        handler=lambda args, **kw: tools.glance_check(args, device=device(), dispatch=ctx.dispatch_tool, **kw),
        description="Diff the simulator screen against the pre-edit baseline", emoji="👀",
    )
    ctx.register_tool(
        name="glance_baseline", toolset="glance", schema=schemas.GLANCE_BASELINE,
        handler=lambda args, **kw: tools.glance_baseline(args, device=device(), **kw),
        description="Save the current simulator screen as the baseline", emoji="📸",
    )
    ctx.register_hook("pre_tool_call", lambda **kw: hooks.pre_tool_call(device=device(), **kw))
    ctx.register_hook("pre_verify", hooks.pre_verify)
    ctx.register_hook("transform_llm_output", hooks.transform_llm_output)
    ctx.register_cli_command(
        name="glance", help="Check that Glance can see a device", setup_fn=cli.setup,
        handler_fn=lambda args: cli.run(args, device()),
    )
    ctx.register_skill(
        "glance", Path(__file__).resolve().parent / "skills" / "glance" / "SKILL.md",
        description="Look at the running app before calling a UI change done",
    )
