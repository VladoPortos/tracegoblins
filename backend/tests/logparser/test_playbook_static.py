from pathlib import Path

from app.logparser import StaticTask, parse_task_file
from app.logparser.playbook_static import module_arg_exprs

FIXTURE = Path(__file__).parent.parent / "fixtures" / "ansible" / "sample_tasks.yml"


def test_empty_and_invalid_return_empty():
    assert parse_task_file("") == []
    assert parse_task_file(":\n  - [unbalanced") == []


def test_parses_tasks_with_lines_actions_when():
    tasks = parse_task_file(FIXTURE.read_text())
    by_name = {t.name: t for t in tasks}

    nginx = by_name["install nginx"]
    assert nginx.line == 2 and nginx.action == "ansible.builtin.apt" and nginx.when is None

    win = by_name["windows only path"]
    assert win.line == 7
    assert win.action == "ansible.windows.win_package"
    assert win.when == 'ansible_os_family == "Windows"'


def test_block_is_emitted_and_its_children_recursed():
    tasks = parse_task_file(FIXTURE.read_text())
    block = next(t for t in tasks if t.is_block)
    assert block.name == "hardening" and block.when == "enable_hardening | bool"
    assert block.parent_line is None  # top-level block
    # the inner task is also enumerated, with its own line, parented to the block
    inner = next(t for t in tasks if t.name == "set sysctl")
    assert inner.action == "ansible.posix.sysctl" and inner.is_block is False
    assert inner.line == 13
    assert inner.parent_line == block.line  # nesting captured for the never-run tree


def test_sorted_by_line():
    tasks = parse_task_file(FIXTURE.read_text())
    lines = [t.line for t in tasks]
    assert lines == sorted(lines)


def test_when_list_is_joined():
    src = ("- name: gated\n"
           "  ansible.builtin.debug: {}\n"
           "  when:\n"
           "    - a\n"
           "    - b\n")
    assert parse_task_file(src)[0].when == "a and b"


def test_multi_document_file_parses_all_docs():
    src = ("- name: one\n  ansible.builtin.debug: {}\n"
           "---\n"
           "- name: two\n  ansible.builtin.debug: {}\n")
    assert [t.name for t in parse_task_file(src)] == ["one", "two"]


def test_play_without_tasks_is_not_emitted_as_a_task():
    # a play header (has `hosts`) with no tasks/roles must NOT show up as a spurious never-run task (NR5)
    src = ("- hosts: all\n"
           "  gather_facts: false\n")
    assert parse_task_file(src) == []


def test_play_with_tasks_descends_and_play_is_not_a_task(self_check=None):
    src = ("- hosts: web\n"
           "  tasks:\n"
           "    - name: real task\n"
           "      ansible.builtin.debug: {}\n")
    tasks = parse_task_file(src)
    assert [t.name for t in tasks] == ["real task"]
    assert all(t.name != "web" for t in tasks)  # the play is not emitted as a task


def test_with_lookup_is_a_directive_not_the_module():
    # `with_nested` etc. are loop directives; even listed BEFORE the module the real action wins (NR6)
    src = ("- name: looped\n"
           "  with_nested:\n"
           "    - [1, 2]\n"
           "  ansible.builtin.copy: {}\n")
    t = parse_task_file(src)[0]
    assert t.action == "ansible.builtin.copy"


def test_play_line_tracks_enclosing_play():
    # NR4: each task carries the line of its enclosing play header so anchoring can stay in-play
    src = ("- hosts: web\n"        # 1
           "  tasks:\n"            # 2
           "    - name: a\n"       # 3
           "      debug: {}\n"     # 4
           "- hosts: db\n"         # 5
           "  tasks:\n"            # 6
           "    - name: b\n"       # 7
           "      debug: {}\n")    # 8
    by_name = {t.name: t for t in parse_task_file(src)}
    assert by_name["a"].play_line == 1
    assert by_name["b"].play_line == 5


def test_play_line_none_for_task_only_file():
    # a roles/x/tasks/main.yml style task list has no play header → play_line None (single scope)
    src = ("- name: a\n  debug: {}\n- name: b\n  debug: {}\n")
    assert all(t.play_line is None for t in parse_task_file(src))


def test_module_arg_exprs_returns_raw_templates():
    # VV-C: raw `{{ }}` exprs per module-arg key, keyed by the task line
    src = ("- name: install\n"            # 1
           "  ansible.builtin.apt:\n"     # 2  (task mapping starts at line 1)
           "    name: \"{{ pkg }}\"\n"    # 3
           "    state: present\n")        # 4
    exprs = module_arg_exprs(src, 1)
    assert exprs["name"] == "{{ pkg }}"
    assert exprs["state"] == "present"
    assert module_arg_exprs(src, 999) == {}   # no task at that line


def test_module_arg_exprs_for_set_fact():
    src = ("- name: derive\n"             # 1
           "  ansible.builtin.set_fact:\n"  # 2
           "    port: \"{{ base + 1 }}\"\n")  # 3
    assert module_arg_exprs(src, 1)["port"] == "{{ base + 1 }}"


def test_block_rescue_always_sections_tracked():
    src = ("- name: b\n"           # 1 (block)
           "  block:\n"            # 2
           "    - name: body\n"    # 3
           "      ansible.builtin.debug: {}\n"   # 4
           "  rescue:\n"           # 5
           "    - name: oops\n"    # 6
           "      ansible.builtin.debug: {}\n"   # 7
           "  always:\n"           # 8
           "    - name: cleanup\n"  # 9
           "      ansible.builtin.debug: {}\n")  # 10
    by_name = {t.name: t for t in parse_task_file(src)}
    assert by_name["b"].is_block and by_name["b"].section is None
    assert by_name["body"].section == "block"
    assert by_name["oops"].section == "rescue"
    assert by_name["cleanup"].section == "always"
