from app.logparser.stdout import parse_stdout


def test_running_handler_opens_a_task():
    out = parse_stdout("PLAY [p] ***\nRUNNING HANDLER [restart nginx] ***\nchanged: [h1]\n")
    assert out.plays[0].tasks[0].name == "restart nginx"
    assert out.plays[0].tasks[0].statuses == {"h1": "changed"}


def test_failed_fatal_sets_error_and_no_output():
    log = ('PLAY [p] ***\nTASK [do thing] ***\n'
           'fatal: [h1]: FAILED! => {"msg": "boom happened", "rc": 2}\n')
    t = parse_stdout(log).plays[0].tasks[0]
    assert t.statuses == {"h1": "failed"}
    assert t.error == "boom happened"
    assert t.output == ""


def test_ignoring_maps_to_failed():
    t = parse_stdout("PLAY [p] ***\nTASK [t] ***\nignoring: [h1]\n").plays[0].tasks[0]
    assert t.statuses == {"h1": "failed"}


def test_role_name_include_sets_no_status():
    log = "PLAY [p] ***\nTASK [inc] ***\nincluded: dxc.xaas.get_info for h1\n"
    t = parse_stdout(log).plays[0].tasks[0]
    assert t.statuses == {} and t.included_path is None


def test_path_include_sets_included_and_path():
    log = "PLAY [p] ***\nTASK [inc] ***\nincluded: /runner/x.yml for h1\n"
    t = parse_stdout(log).plays[0].tasks[0]
    assert t.statuses == {"h1": "included"} and t.included_path == "/runner/x.yml"


def test_loop_host_status_is_worst_item_not_first(XMOD1=None):
    # XMOD1: a later FAILED loop item must override an earlier ok/changed for the same host —
    # otherwise a failed run is misclassified green on the Status Map.
    log = ("PLAY [p] ***\nTASK [install] ***\n"
           "ok: [h1] => (item=a)\n"
           "changed: [h1] => (item=b)\n"
           "failed: [h1] => (item=c)\n")
    t = parse_stdout(log).plays[0].tasks[0]
    assert t.statuses == {"h1": "failed"} and t.items == 3
    assert t.dominant() == "failed"


def test_loop_host_status_keeps_worst_when_failure_is_first():
    # symmetric: an early failure is not downgraded by a later ok
    log = ("PLAY [p] ***\nTASK [install] ***\n"
           "failed: [h1] => (item=a)\n"
           "ok: [h1] => (item=b)\n")
    t = parse_stdout(log).plays[0].tasks[0]
    assert t.statuses == {"h1": "failed"}


def test_output_capture_with_item_and_cap():
    big = "x" * 5000
    blob_line = '    "blob": "' + big + '"'
    log = 'PLAY [p] ***\nTASK [t] ***\nok: [h1] => (item=a) => {\n' + blob_line + '\n}\n\n'
    t = parse_stdout(log).plays[0].tasks[0]
    assert t.items == 1 and t.statuses == {"h1": "ok"}
    assert len(t.output) == 1200


def test_recap_with_rescued_ignored():
    log = ("PLAY RECAP ***\n"
           "h1                         : ok=3 changed=1 unreachable=0 failed=0 "
           "skipped=2 rescued=1 ignored=1\n")
    r = parse_stdout(log).recap[0]
    assert (r.host, r.ok, r.rescued, r.ignored) == ("h1", 3, 1, 1)


def test_play_recap_is_not_a_play():
    out = parse_stdout("PLAY [only one] ***\nTASK [t] ***\nok: [h1]\nPLAY RECAP ***\nh1 : ok=1\n")
    assert len(out.plays) == 1  # RECAP must not create a play
