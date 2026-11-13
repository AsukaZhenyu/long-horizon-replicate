"""Method adapters.

Each adapter only maps the method's native action/observation schema to the
common contract.  It delegates the loop to the native agent unchanged.
"""
from __future__ import annotations

from contract.types import MethodAdapter, NativeAgent


class PassThroughAdapter(MethodAdapter):
    name = ""
    mechanism = ()
    adapter_changes = (
        "action schema -> common Action",
        "native observation -> common Observation",
        "native submit -> common submit",
    )

    def __init__(self, native: NativeAgent):
        super().__init__(native)


class BaseAgentAdapter(PassThroughAdapter):
    name = "base"
    mechanism = ()
    adapter_changes = ()
    native_loop_ready = True


class SentryAdapter(PassThroughAdapter):
    name = "sentry"
    mechanism = ("detector", "verifier", "updater")
    native_loop_ready = True


class SpineAdapter(PassThroughAdapter):
    name = "spine"
    mechanism = ("spine_open", "spine_close", "spine_next", "spine_spawn")
    # The official Pi/Node plugin is not bridged into the Python Host contract.
    # ``SpineReimplementationAdapter`` below is a separate, clearly labeled
    # Python reimplementation used for mechanism smoke tests.


class SpineReimplementationAdapter(PassThroughAdapter):
    name = "spine-reimpl"
    mechanism = ("spine_open", "spine_close", "spine_next", "spine_spawn")
    adapter_changes = (
        "official Pi/Node plugin -> Python subtask-tree reimplementation",
        "spine_* tool calls -> tree transitions",
        "closed-branch history -> memory in the context",
    )
    native_loop_ready = True
    reimplemented = True


class RecurisAdapter(PassThroughAdapter):
    name = "recuris"
    mechanism = ("memory_retrieve", "memory_update", "completion_gate")
    native_loop_ready = True


class RRSIAdapter(PassThroughAdapter):
    name = "rrsi"
    mechanism = ("harness_edit", "search_selection")
    # The Evaluate half is local; the search loop still needs a strong model /
    # Vertex.  Marked ready for the adapter's actual mechanism, not the loop.
    native_loop_ready = True


class OpenJiuwenAdapter(PassThroughAdapter):
    name = "openjiuwen"
    mechanism = ("inner_loop", "outer_loop", "rails")


class LHHAdapter(PassThroughAdapter):
    name = "lhh"
    mechanism = ("manage", "execute", "audit")


class OperaAdapter(PassThroughAdapter):
    name = "opera"
    mechanism = ("critic_trigger", "critic_audit", "resolution_tracking")


METHOD_ADAPTERS = (
    BaseAgentAdapter,
    SentryAdapter,
    SpineAdapter,
    RecurisAdapter,
    RRSIAdapter,
    OpenJiuwenAdapter,
    LHHAdapter,
    OperaAdapter,
)


def build_base(client, **kwargs):
    from agents.base_react import BaseReactAgent
    return BaseAgentAdapter(BaseReactAgent(client, **kwargs))


def build_sentry(client, **kwargs):
    from agents.sentry import SentryAgent
    return SentryAdapter(SentryAgent(client, **kwargs))


def build_recuris(client, **kwargs):
    from agents.recuris import RecurisAgent
    return RecurisAdapter(RecurisAgent(client, **kwargs))


def build_rrsi(client, **kwargs):
    from agents.rrsi import RRSIPromptAgent
    return RRSIAdapter(RRSIPromptAgent(client, **kwargs))


def build_spine_reimpl(client, **kwargs):
    from agents.spine import SpineAgent
    return SpineReimplementationAdapter(SpineAgent(client, **kwargs))


METHOD_BUILDERS = {
    "base": build_base,
    "sentry": build_sentry,
    "recuris": build_recuris,
    "rrsi": build_rrsi,
}

EXTRA_BUILDERS = {
    "spine-reimpl": build_spine_reimpl,
}
