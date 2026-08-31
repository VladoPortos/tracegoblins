# Synthetic AWX/ansible-runner job_events fixture (linear strategy; created stamps
# spaced by whole seconds so durations are exact). Real captures arrive in M4.
SAMPLE_JOB_EVENTS: list[dict] = [
    {"event": "playbook_on_start", "created": "2026-06-03T10:00:00.000000Z",
     "event_data": {"playbook": "site.yml"}},
    {"event": "playbook_on_play_start", "created": "2026-06-03T10:00:01.000000Z",
     "event_data": {"play": "Configure web tier", "play_uuid": "p1"}},

    {"event": "playbook_on_task_start", "created": "2026-06-03T10:00:02.000000Z",
     "event_data": {"play": "Configure web tier", "task": "Install nginx",
                    "role": "webserver", "task_uuid": "t1"}},
    {"event": "runner_on_ok", "created": "2026-06-03T10:00:04.000000Z", "host": "web01",
     "event_data": {"task": "Install nginx", "task_uuid": "t1", "host": "web01",
                    "res": {"changed": False, "msg": "nginx present"}}},

    {"event": "playbook_on_task_start", "created": "2026-06-03T10:00:05.000000Z",
     "event_data": {"play": "Configure web tier", "task": "Deploy vhosts",
                    "role": "webserver", "task_uuid": "t2"}},
    {"event": "runner_item_on_ok", "created": "2026-06-03T10:00:05.500000Z", "host": "web01",
     "event_data": {"task_uuid": "t2", "host": "web01", "event_loop": "vhosts",
                    "res": {"changed": False, "item": "default"}}},
    {"event": "runner_item_on_ok", "created": "2026-06-03T10:00:06.000000Z", "host": "web01",
     "event_data": {"task_uuid": "t2", "host": "web01", "event_loop": "vhosts",
                    "res": {"changed": True, "item": "api"}}},
    {"event": "runner_item_on_skipped", "created": "2026-06-03T10:00:06.500000Z", "host": "web01",
     "event_data": {"task_uuid": "t2", "host": "web01", "event_loop": "vhosts",
                    "res": {"skipped": True, "item": "legacy"}}},
    {"event": "runner_on_ok", "created": "2026-06-03T10:00:08.000000Z", "host": "web01",
     "event_data": {"task": "Deploy vhosts", "task_uuid": "t2", "host": "web01",
                    "res": {"changed": True, "msg": "2 vhosts updated"}}},

    {"event": "playbook_on_task_start", "created": "2026-06-03T10:00:09.000000Z",
     "event_data": {"play": "Configure web tier", "task": "Restart nginx",
                    "role": "webserver", "task_uuid": "t3"}},
    {"event": "runner_on_unreachable", "created": "2026-06-03T10:00:10.000000Z", "host": "web02",
     "event_data": {"task": "Restart nginx", "task_uuid": "t3", "host": "web02",
                    "res": {"unreachable": True, "changed": False,
                            "msg": "Failed to connect to the host via ssh: "
                                   "ssh: connect to host web02 port 22: No route to host"}}},

    {"event": "playbook_on_stats", "created": "2026-06-03T10:00:11.000000Z",
     "event_data": {"ok": {"web01": 2}, "changed": {"web01": 1}, "dark": {"web02": 1},
                    "failures": {}, "skipped": {}, "rescued": {}, "ignored": {},
                    "processed": {"web01": 1, "web02": 1}}},
]
