"""Real Ansible `tasks.error` blobs from §0 of the M5 Canonical Contract.

Reused across the Phase C matcher + service tests. Two SSH blobs share the same
host IP but DIFFERENT /tmp/ansible.<rand>_ssh_cert paths -> they must normalize to
ONE signature with identical representative_text (the abs-path strip collapses them).
"""
from __future__ import annotations

# 1 — SSH connect, host A path /tmp/ansible._7oamnkx_ssh_cert
SSH_BLOB_A = (
    '{"changed": false, "msg": "Failed to connect to the host via ssh: '
    "Warning: Permanently added '100.66.0.108' (ED25519) to the list of known hosts."
    "\\r\\nAuthorized users only. All activity may be monitored and reported."
    '\\nLoad key \\"/tmp/ansible._7oamnkx_ssh_cert\\": invalid format'
    "\\r\\ncloudauto@100.66.0.108: Permission denied (publickey,password)."
    '"}'
)

# 2 — SSH connect, host B path /tmp/ansible.kgrju_2v_ssh_cert (DIFFERENT path, same shape)
SSH_BLOB_B = (
    '{"changed": false, "msg": "Failed to connect to the host via ssh: '
    "Warning: Permanently added '100.66.0.108' (ED25519) to the list of known hosts."
    "\\r\\nAuthorized users only. All activity may be monitored and reported."
    '\\nLoad key \\"/tmp/ansible.kgrju_2v_ssh_cert\\": invalid format'
    "\\r\\ncloudauto@100.66.0.108: Permission denied (publickey,password)."
    '"}'
)

# 3 — WinRM / NTLM
WINRM_BLOB = (
    '{"changed": false, "msg": "ntlm: HTTPSConnectionPool(host=\'100.70.7.24\', '
    "port=5986): Max retries exceeded with url: /wsman (Caused by "
    "NewConnectionError('<urllib3.connection.HTTPSConnection object at "
    "0x7fc18f7eaa50>: Failed to establish a new connection: [Errno 113] "
    'No route to host\'))", "unreachable": true}'
)

# 4 — assertion failed (AWX job 745 runner_on_failed event_data.res)
ASSERT_BLOB = (
    '{"_ansible_verbose_always": true, "evaluated_to": false, '
    '"assertion": "(resources.count | default(0)) > 0", '
    "\"msg\": \"Resource 'd2a-throwaway-del' not found in CDB for "
    'organization \'acmeco\'", "changed": false}'
)
