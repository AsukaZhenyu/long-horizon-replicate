"""A Python reimplementation of Spine's subtask-tree protocol.

This is **not** the official ``@spinejit/pi-spinejit`` Pi plugin.  The official
plugin is a Node/Pi extension; bridging it into the Python ``Host`` contract
would require a per-action RPC proxy.  This module reimplements the part the
ablation needs to be observable:

- explicit branches opened with a goal and closed with a memory;
- the active branch is the innermost unclosed node;
- ``spine_open`` enters a child, ``spine_close`` returns one level,
  ``spine_next`` closes the current branch and enters a sibling;
- finished branches' raw history is dropped and replaced by their memory in
  the context shown to the model;
- ``spine_spawn`` is recognised and counted but not executed (concurrent child
  agents are outside this reimplementation).

The instructions and tool descriptions are adapted from the upstream
``packages/sdk/spine.toml``.  Report this as ``reimplemented``, never as the
native plugin.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List

from agents.base_react import ACTION_PROTOCOL, ModelClient, ModelRequestError, parse_action
from contract.types import Action, Host, NativeAgent, Observation, TaskSpec

SPINE_INSTRUCTION = """<spine_instruction>
All substantive work MUST take place within explicit SpineBranches.

Use recursive calls: each branch owns one outcome. Work toward that outcome there, including synthesis and routine checks. Open a direct child for a distinct unresolved subproblem needed for that outcome, and apply the same rule inside it.

The active branch is the innermost unclosed <spine_node>. spine_open enters its child. spine_close returns exactly one level. spine_next returns one level and enters a sibling under that parent. <spine_memory> carries a returned result. Runtime replaces completed local history with that memory.

When the local outcome is complete or cancelled, close the branch with its result. Continue in the parent; if its outcome is also complete, close it too. For new work, first reach the branch whose goal directly needs it, then open its child. Use spine_next only when that owner is your immediate parent. State the intended outcome in each goal.

Memory adds what continuation needs beyond inherited context and retained child results: local findings, changed conclusions, synthesis, and remaining obligations. Preserve necessary evidence and referents.

Root coordinates; enter a branch before substantive work. Answer the user in any scope.
</spine_instruction>"""

SPINE_TOOLS = """Spine tool actions (one action per turn, same JSON object):
- {"spine_open": {"goal": "..."}}    enter a direct child for goal
- {"spine_close": {"memory": "..."}} finalize the local scope and return to the parent
- {"spine_next": {"memory": "...", "goal": "..."}} finalize and enter a sibling
- {"spine_spawn": {"tasks": [...]}}  recognized; not executed in this reimplementation

Terminal actions:
- {"command": "..."}  run a shell command in the task environment
- {"final": "..."}    submit the result
""" + ACTION_PROTOCOL


@dataclass
class SpineNode:
    node_id: str
    goal: str
    parent: "SpineNode | None" = None
    memory: str = ""
    closed: bool = False
    children: List["SpineNode"] = field(default_factory=list)


class SpineError(ValueError):
    pass


class SpineTree:
    def __init__(self, root_goal: str):
        self.root = SpineNode("1", root_goal)
        self.active = self.root
        self.counters: Counter = Counter()

    def _child_id(self, parent: SpineNode) -> str:
        return f"{parent.node_id}.{len(parent.children) + 1}"

    def open(self, goal: str) -> SpineNode:
        goal = str(goal or "").strip()
        if not goal:
            raise SpineError("spine_open requires a nonempty goal")
        node = SpineNode(self._child_id(self.active), goal, parent=self.active)
        self.active.children.append(node)
        self.active = node
        self.counters["spine_open"] += 1
        return node

    def close(self, memory: str) -> SpineNode:
        if self.active is self.root:
            raise SpineError("root cannot close")
        if not str(memory or "").strip():
            raise SpineError("spine_close requires a nonempty memory")
        node = self.active
        node.memory = str(memory).strip()
        node.closed = True
        self.active = node.parent
        self.counters["spine_close"] += 1
        return node

    def next(self, memory: str, goal: str) -> SpineNode:
        if self.active is self.root:
            raise SpineError("root cannot next")
        if not str(memory or "").strip():
            raise SpineError("spine_next requires a nonempty memory")
        goal = str(goal or "").strip()
        if not goal:
            raise SpineError("spine_next requires a nonempty goal")
        node = self.active
        parent = node.parent
        node.memory = str(memory).strip()
        node.closed = True
        sibling = SpineNode(self._child_id(parent), goal, parent=parent)
        parent.children.append(sibling)
        self.active = sibling
        self.counters["spine_next"] += 1
        return sibling

    def spawn(self, tasks: Any) -> None:
        # The official spawn runs concurrent child agents.  This
        # reimplementation records the attempt but does not execute it.
        self.counters["spine_spawn_unsupported"] += 1
        raise SpineError(
            "spine_spawn is not implemented in this reimplementation; "
            "use spine_open/spine_next")

    def render(self) -> str:
        lines = ["<spine_context>", f"active: {self.active.node_id}"]
        for node in self._walk(self.root):
            depth = node.node_id.count(".")
            status = "closed" if node.closed else (
                "active" if node is self.active else "open")
            lines.append(
                f"{'  ' * depth}{node.node_id} [{status}] {node.goal}")
            if node.closed:
                lines.append(f"{'  ' * (depth + 1)}memory: {node.memory}")
        lines.append("</spine_context>")
        return "\n".join(lines)

    def _walk(self, node: SpineNode):
        yield node
        for child in node.children:
            yield from self._walk(child)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "active": self.active.node_id,
            "counters": dict(self.counters),
            "nodes": [
                {
                    "id": node.node_id,
                    "goal": node.goal,
                    "parent": node.parent.node_id if node.parent else None,
                    "closed": node.closed,
                    "memory": node.memory,
                }
                for node in self._walk(self.root)
            ],
        }


class SpineAgent(NativeAgent):
    """Reimplemented Spine loop over the common terminal ``Host``."""

    name = "spine-reimpl"
    mechanism = ("spine_open", "spine_close", "spine_next", "spine_spawn")
    reimplemented = True

    def __init__(self, client: ModelClient, max_steps: int = 40):
        self.client = client
        self.max_steps = max_steps
        self.tree: SpineTree | None = None
        self.tree_snapshot: Dict[str, Any] = {}
        self.spine_actions: Counter = Counter()
        self.turns = 0
        self.last_error = ""

    def _system_prompt(self) -> str:
        return (SPINE_INSTRUCTION + "\n\n" + SPINE_TOOLS + "\n\n"
                + self.tree.render())

    def run(self, task: TaskSpec, host: Host) -> None:
        self.tree = SpineTree(task.instruction)
        node_log: Dict[str, List[dict]] = {"1": []}
        try:
            for _ in range(self.max_steps):
                messages = [
                    {"role": "system", "content": self._system_prompt()},
                    {"role": "user", "content": task.instruction},
                    *node_log.get(self.tree.active.node_id, []),
                ]
                try:
                    response = self.client.complete(messages)
                except ModelRequestError as exc:
                    self.last_error = str(exc)
                    return
                try:
                    self._charge(host, response.total_tokens)
                except RuntimeError as exc:
                    self.last_error = str(exc)
                    return
                self.turns += 1
                active_id = self.tree.active.node_id
                node_log.setdefault(active_id, []).append(
                    {"role": "assistant", "content": response.content})
                try:
                    action = parse_action(response.content)
                except (ValueError, TypeError) as exc:
                    node_log[active_id].append(
                        {"role": "user", "content": f"Invalid JSON: {exc}"})
                    continue
                if not isinstance(action, dict):
                    node_log[active_id].append(
                        {"role": "user", "content": "Action must be one JSON object."})
                    continue
                keys = set(action) & {
                    "spine_open", "spine_close", "spine_next", "spine_spawn",
                    "command", "final",
                }
                if len(keys) != 1:
                    node_log[active_id].append({
                        "role": "user",
                        "content": "Choose exactly one of spine_open, spine_close, "
                                   "spine_next, spine_spawn, command, final.",
                    })
                    continue
                key = next(iter(keys))
                if key == "spine_open":
                    self._handle_spine_open(action[key], node_log, active_id)
                    continue
                if key == "spine_close":
                    self._handle_spine_close(action[key], node_log, active_id)
                    continue
                if key == "spine_next":
                    self._handle_spine_next(action[key], node_log, active_id)
                    continue
                if key == "spine_spawn":
                    self.spine_actions["spine_spawn"] += 1
                    try:
                        self.tree.spawn(action[key])
                    except SpineError as exc:
                        node_log[active_id].append(
                            {"role": "user", "content": f"spine_spawn: {exc}"})
                    continue
                if key == "command":
                    command = str(action["command"])
                    observation = host.step(Action("shell", {"command": command}))
                    node_log[active_id].append({
                        "role": "user",
                        "content": self._render(observation),
                    })
                    continue
                if key == "final":
                    host.submit()
                    return
        finally:
            if self.tree is not None:
                self.tree_snapshot = self.tree.snapshot()
                self.spine_actions = Counter(self.tree.counters)

    def _handle_spine_open(self, payload: Any, node_log, active_id: str) -> None:
        goal = payload.get("goal") if isinstance(payload, dict) else payload
        try:
            node = self.tree.open(goal)
        except SpineError as exc:
            node_log[active_id].append(
                {"role": "user", "content": f"spine_open: {exc}"})
            return
        node_log.setdefault(node.node_id, [])

    def _handle_spine_close(self, payload: Any, node_log, active_id: str) -> None:
        memory = payload.get("memory") if isinstance(payload, dict) else payload
        try:
            node = self.tree.close(memory)
        except SpineError as exc:
            node_log[active_id].append(
                {"role": "user", "content": f"spine_close: {exc}"})
            return
        # Drop the closed branch's raw history; the parent sees its memory in
        # the tree render instead.
        node_log.pop(node.node_id, None)

    def _handle_spine_next(self, payload: Any, node_log, active_id: str) -> None:
        if not isinstance(payload, dict):
            node_log[active_id].append(
                {"role": "user", "content": "spine_next requires memory and goal."})
            return
        try:
            node = self.tree.next(payload.get("memory", ""), payload.get("goal", ""))
        except SpineError as exc:
            node_log[active_id].append(
                {"role": "user", "content": f"spine_next: {exc}"})
            return
        node_log.pop(active_id, None)
        node_log.setdefault(node.node_id, [])

    @staticmethod
    def _charge(host: Host, tokens: int) -> None:
        charge = getattr(host, "charge_tokens", None)
        if callable(charge):
            charge(tokens)

    @staticmethod
    def _render(observation: Observation) -> str:
        return f"exit={observation.exit_code}\n{observation.output}\n{observation.error}"
