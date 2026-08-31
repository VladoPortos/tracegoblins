from app.api.path_schemas import PathNodeOut
from app.services.path_forks import synthesize_forks


def _n(nid, *, cond=False, status="ok"):
    return PathNodeOut(id=nid, type="task", label=nid, status=status, is_conditional=cond)


def test_two_disjoint_conditionals_become_a_fork():
    nodes = [_n("a"), _n("yum", cond=True), _n("choco", cond=True), _n("z")]
    taken = {"yum": {"rhel1", "rhel2"}, "choco": {"win1"}}
    out, edges = synthesize_forks(nodes, taken)
    when = next(n for n in out if n.type == "when")
    assert when.is_conditional and when.branch is None
    yum_node = next(n for n in out if n.id == "yum")
    choco_node = next(n for n in out if n.id == "choco")
    assert yum_node.branch == "yum"
    assert choco_node.branch == "choco"
    # taken_hosts must be the sorted list of hosts that ran each branch
    assert yum_node.taken_hosts == ["rhel1", "rhel2"]
    assert choco_node.taken_hosts == ["win1"]
    pairs = {(e.from_, e.to, e.branch) for e in edges}
    assert ("a", when.id, None) in pairs           # predecessor -> when
    assert (when.id, "yum", "yum") in pairs         # when -> each branch (branch-tagged)
    assert (when.id, "choco", "choco") in pairs
    assert ("yum", "z", "yum") in pairs             # each branch -> common successor
    assert ("choco", "z", "choco") in pairs


def test_single_conditional_stays_linear():
    nodes = [_n("a"), _n("rh", cond=True), _n("z")]
    out, edges = synthesize_forks(nodes, {"rh": {"rhel1"}})
    assert all(n.type != "when" for n in out)
    pairs = {(e.from_, e.to) for e in edges}
    assert ("a", "rh") in pairs and ("rh", "z") in pairs


def test_overlapping_hosts_not_forked():
    nodes = [_n("x", cond=True), _n("y", cond=True)]
    out, _ = synthesize_forks(nodes, {"x": {"h1", "h2"}, "y": {"h2"}})  # h2 in both -> not disjoint
    assert all(n.type != "when" for n in out)


def test_no_conditionals_is_pure_linear():
    nodes = [_n("a"), _n("b"), _n("c")]
    out, edges = synthesize_forks(nodes, {})
    assert [n.id for n in out] == ["a", "b", "c"]
    assert [(e.from_, e.to) for e in edges] == [("a", "b"), ("b", "c")]
