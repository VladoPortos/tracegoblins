"""Pure, file-scoped static parser for a single Ansible task/playbook YAML file.

Given one file's text it returns the tasks (and blocks) it defines, each with its
1-based source line. NO include/import/role-graph resolution — that is intentional
(M3 file-scoped diff). No DB/HTTP. Line numbers come from PyYAML's compose marks.
"""
from __future__ import annotations

from dataclasses import dataclass

import yaml

# Keys that are task-level directives, NOT the module being invoked.
_DIRECTIVES = {
    "name", "when", "with_items", "with_dict", "with_fileglob", "with_together",
    "loop", "loop_control", "register", "tags", "become", "become_user", "become_method",
    "vars", "notify", "delegate_to", "delegate_facts", "run_once", "ignore_errors",
    "ignore_unreachable", "changed_when", "failed_when", "check_mode", "diff",
    "environment", "no_log", "args", "block", "rescue", "always", "until", "retries",
    "delay", "listen", "any_errors_fatal", "throttle", "timeout", "connection",
    "remote_user", "module_defaults", "collections", "action", "local_action",
}
_PLAY_TASK_KEYS = ("pre_tasks", "tasks", "post_tasks", "handlers")
_BLOCK_KEYS = ("block", "rescue", "always")
# include/import directives whose target file/role we capture for never-run coverage (NR2).
_INCLUDE_ACTIONS = {
    "include_tasks", "import_tasks", "include_role", "import_role", "include",
    "ansible.builtin.include_tasks", "ansible.builtin.import_tasks",
    "ansible.builtin.include_role", "ansible.builtin.import_role", "ansible.builtin.include",
}


@dataclass(frozen=True)
class StaticTask:
    line: int                 # 1-based source line of the task / block
    name: str | None
    action: str | None        # module key, e.g. "ansible.builtin.apt"; None for blocks
    when: str | None          # raw `when:` expression text, if present
    is_block: bool = False
    parent_line: int | None = None  # line of the enclosing block; None = top-level of the file/play
    section: str | None = None      # which part of the enclosing block: block | rescue | always
    play_line: int | None = None    # line of the enclosing play header; None in task-only files
    target: str | None = None       # include/import target (file or role name), for never-run coverage


def _line_of(node: yaml.nodes.Node) -> int:
    return node.start_mark.line + 1


def _scalar(node: yaml.nodes.Node | None) -> str | None:
    if isinstance(node, yaml.ScalarNode):
        return str(node.value)
    return None


def _when(node: yaml.nodes.Node | None) -> str | None:
    """A `when:` may be a scalar or a YAML list of conditions (implicitly AND-ed by Ansible).
    Join list conditions with ' and ' so a list-form `when` keeps its condition on the ghost."""
    if isinstance(node, yaml.ScalarNode):
        return str(node.value)
    if isinstance(node, yaml.SequenceNode):
        parts = [str(c.value) for c in node.value if isinstance(c, yaml.ScalarNode)]
        return " and ".join(parts) if parts else None
    return None


def _keymap(mapping: yaml.MappingNode) -> dict[str, yaml.nodes.Node]:
    return {k.value: v for k, v in mapping.value if isinstance(k, yaml.ScalarNode)}


def parse_task_file(text: str) -> list[StaticTask]:
    try:
        docs = list(yaml.compose_all(text, Loader=yaml.SafeLoader))
    except yaml.YAMLError:
        return []
    out: list[StaticTask] = []
    for root in docs:  # compose_all handles multi-document files; marks stay file-absolute
        if root is not None:
            _walk(root, out, None, None, None)
    out.sort(key=lambda t: t.line)
    return out


def module_arg_exprs(text: str, line: int) -> dict[str, str]:
    """Raw `{{ }}` exprs for the module args of the task whose mapping starts at `line`, keyed by
    arg name (VV-C provenance). Handles the mapping form (`module:\\n  k: v`); returns {} when the
    task isn't found or its module value isn't a mapping. Pure."""
    try:
        docs = list(yaml.compose_all(text, Loader=yaml.SafeLoader))
    except yaml.YAMLError:
        return {}
    out: dict[str, str] = {}

    def visit(node: yaml.nodes.Node) -> None:
        if isinstance(node, yaml.SequenceNode):
            for it in node.value:
                visit(it)
        elif isinstance(node, yaml.MappingNode):
            if _line_of(node) == line and not out:
                for k, v in node.value:  # the module is the first non-directive, non-with_ key
                    if isinstance(k, yaml.ScalarNode) and k.value not in _DIRECTIVES \
                            and not k.value.startswith("with_"):
                        if isinstance(v, yaml.MappingNode):
                            for mk, mv in v.value:
                                if isinstance(mk, yaml.ScalarNode) and isinstance(mv, yaml.ScalarNode):
                                    out[mk.value] = str(mv.value)
                        break
            for _k, v in node.value:
                visit(v)

    for d in docs:
        if d is not None:
            visit(d)
    return out


def _include_target(action: str, value: yaml.nodes.Node | None) -> str | None:
    """The target file/role of an include/import directive, from its scalar value
    (`include_tasks: x.yml`) or mapping value (`include_role: {name: x}`). None otherwise."""
    if action not in _INCLUDE_ACTIONS:
        return None
    if isinstance(value, yaml.ScalarNode):
        return str(value.value)
    if isinstance(value, yaml.MappingNode):
        m = _keymap(value)
        for tk in ("file", "name"):
            if isinstance(m.get(tk), yaml.ScalarNode):
                return str(m[tk].value)
    return None


def _walk(node: yaml.nodes.Node, out: list[StaticTask],
          parent_line: int | None, section: str | None, play_line: int | None) -> None:
    if isinstance(node, yaml.SequenceNode):
        for item in node.value:
            _walk_item(item, out, parent_line, section, play_line)
    elif isinstance(node, yaml.MappingNode):
        keys = _keymap(node)
        pl = _line_of(node) if "hosts" in keys else play_line  # a bare-mapping play sets the scope
        for tk in _PLAY_TASK_KEYS:
            if tk in keys:
                _walk(keys[tk], out, parent_line, None, pl)


def _walk_item(item: yaml.nodes.Node, out: list[StaticTask],
               parent_line: int | None, section: str | None, play_line: int | None) -> None:
    if not isinstance(item, yaml.MappingNode):
        return
    keys = _keymap(item)
    # block / rescue / always construct → emit the block, then recurse each part with its section
    if any(bk in keys for bk in _BLOCK_KEYS):
        line = _line_of(item)
        out.append(StaticTask(line=line, name=_scalar(keys.get("name")),
                              action=None, when=_when(keys.get("when")), is_block=True,
                              parent_line=parent_line, section=section, play_line=play_line))
        for bk in _BLOCK_KEYS:
            if bk in keys:
                _walk(keys[bk], out, line, bk, play_line)
        return
    # play construct (any mapping with `hosts`) → descend into its task keys, never emit as a task.
    # Note: even a play with no tasks/roles must not be emitted (NR5) — a bare `- hosts:` header.
    if "hosts" in keys:
        pl = _line_of(item)
        for tk in _PLAY_TASK_KEYS:
            if tk in keys:
                _walk(keys[tk], out, parent_line, None, pl)
        return
    # otherwise a task: the module is the first key that is not a directive (and not a with_* lookup, NR6)
    action: str | None = None
    for k, _v in item.value:
        if isinstance(k, yaml.ScalarNode) and k.value not in _DIRECTIVES \
                and not k.value.startswith("with_"):
            action = k.value
            break
    out.append(StaticTask(line=_line_of(item), name=_scalar(keys.get("name")),
                          action=action, when=_when(keys.get("when")), is_block=False,
                          parent_line=parent_line, section=section, play_line=play_line,
                          target=_include_target(action, keys.get(action)) if action else None))
