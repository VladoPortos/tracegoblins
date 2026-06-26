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


@dataclass(frozen=True)
class StaticTask:
    line: int                 # 1-based source line of the task / block
    name: str | None
    action: str | None        # module key, e.g. "ansible.builtin.apt"; None for blocks
    when: str | None          # raw `when:` expression text, if present
    is_block: bool = False
    parent_line: int | None = None  # line of the enclosing block; None = top-level of the file/play


def _line_of(node: yaml.nodes.Node) -> int:
    return node.start_mark.line + 1


def _scalar(node: yaml.nodes.Node | None) -> str | None:
    if isinstance(node, yaml.ScalarNode):
        return str(node.value)
    return None


def _keymap(mapping: yaml.MappingNode) -> dict[str, yaml.nodes.Node]:
    return {k.value: v for k, v in mapping.value if isinstance(k, yaml.ScalarNode)}


def parse_task_file(text: str) -> list[StaticTask]:
    try:
        root = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError:
        return []
    out: list[StaticTask] = []
    if root is not None:
        _walk(root, out, None)
    out.sort(key=lambda t: t.line)
    return out


def _walk(node: yaml.nodes.Node, out: list[StaticTask], parent_line: int | None) -> None:
    if isinstance(node, yaml.SequenceNode):
        for item in node.value:
            _walk_item(item, out, parent_line)
    elif isinstance(node, yaml.MappingNode):
        keys = _keymap(node)
        for tk in _PLAY_TASK_KEYS:
            if tk in keys:
                _walk(keys[tk], out, parent_line)


def _walk_item(item: yaml.nodes.Node, out: list[StaticTask], parent_line: int | None) -> None:
    if not isinstance(item, yaml.MappingNode):
        return
    keys = _keymap(item)
    # block / rescue / always construct → emit the block, then recurse its children under it
    if any(bk in keys for bk in _BLOCK_KEYS):
        line = _line_of(item)
        out.append(StaticTask(line=line, name=_scalar(keys.get("name")),
                              action=None, when=_scalar(keys.get("when")), is_block=True,
                              parent_line=parent_line))
        for bk in _BLOCK_KEYS:
            if bk in keys:
                _walk(keys[bk], out, line)
        return
    # play construct (hosts + a task-bearing key) → descend, do not emit as a task
    if "hosts" in keys and any(k in keys for k in (*_PLAY_TASK_KEYS, "roles")):
        for tk in _PLAY_TASK_KEYS:
            if tk in keys:
                _walk(keys[tk], out, parent_line)
        return
    # otherwise a task: the module is the first key that is not a directive
    action: str | None = None
    for k, _v in item.value:
        if isinstance(k, yaml.ScalarNode) and k.value not in _DIRECTIVES:
            action = k.value
            break
    out.append(StaticTask(line=_line_of(item), name=_scalar(keys.get("name")),
                          action=action, when=_scalar(keys.get("when")), is_block=False,
                          parent_line=parent_line))
