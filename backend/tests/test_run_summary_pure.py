"""Pure tests for build_summary_md — no DB, just in-memory ORM instances."""
from app.models import Run, RunNode, RunNodeResult
from app.services.run_summary import build_summary_md


def _nodes():
    return [
        RunNode(node_id="root", parent_node_id=None, counter=0, node_type="playbook",
                name="pb", status="failed"),
        RunNode(node_id="play-1", parent_node_id="root", counter=1, node_type="play",
                name="Deploy", status="failed"),
        RunNode(node_id="role-1", parent_node_id="play-1", counter=2, node_type="role",
                name="nginx", status="failed"),
        RunNode(node_id="ok-task", parent_node_id="role-1", counter=3, node_type="task",
                name="install pkg", status="ok", action="ansible.builtin.apt"),
        RunNode(node_id="bad-task", parent_node_id="role-1", counter=4, node_type="task",
                name="start service", status="failed", action="ansible.builtin.service",
                host_count=1),
    ]


def test_summary_has_header_recap_and_failure_path():
    run = Run(template_name="Deploy nginx", status="failed", host_count=2, elapsed=12.4,
              awx_job_id="745", scm_revision="abc123def456789", awx_limit="batch_1",
              recap=[{"host": "web1", "ok": 3, "changed": 1, "failed": 1,
                      "unreachable": 0, "skipped": 0}])
    results = [
        RunNodeResult(node_id="bad-task", host="web1", status="failed",
                      result={"msg": "Could not start nginx: address already in use"}),
    ]
    md = build_summary_md(run, _nodes(), results)

    assert md.startswith("# Run summary: Deploy nginx")
    assert "**Status:** failed" in md
    assert "**Job:** #745" in md
    assert "`abc123def456`" in md            # revision truncated to 12 chars
    assert "| web1 |" in md                  # recap row
    # path-to-failure breadcrumb + error excerpt; ok task is NOT listed
    assert "Deploy › nginx › start service" in md
    assert "ansible.builtin.service" in md
    assert "address already in use" in md
    assert "install pkg" not in md.split("## Failures")[1]


def test_summary_no_failures_section_when_clean():
    run = Run(template_name="Smoke", status="successful", host_count=1, recap=[])
    nodes = [
        RunNode(node_id="root", parent_node_id=None, counter=0, node_type="playbook",
                name="pb", status="ok"),
        RunNode(node_id="t", parent_node_id="root", counter=1, node_type="task",
                name="ping", status="ok"),
    ]
    md = build_summary_md(run, nodes, [])
    assert "No task failures recorded." in md
    assert "**Job:**" not in md  # awx_job_id is None → line omitted
