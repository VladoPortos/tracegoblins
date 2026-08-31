"""Ground-truth Ansible error blobs for the normalizer goldens (Contract §0).

Two real tasks.error storage shapes are represented:
  * SSH_*_JSON / WINRM_JSON / ASSERT_JSON  -> json.dumps(res), the job_events shape
  * SSH_*_MSG                              -> the bare Ansible `msg` string, stdout shape

The two SSH cases share IP 100.66.0.108 but differ ONLY in the /tmp/ansible.<rand>
path (host A = _7oamnkx, host B = kgrju_2v). The abs-path strip is what collapses
them to one representative_text; the IP strip alone is not sufficient.
"""

# --- SSH connect failure, host A (path .../ansible._7oamnkx_ssh_cert) ---
SSH_A_MSG = (
    "Failed to connect to the host via ssh: Warning: Permanently added "
    "'100.66.0.108' (ED25519) to the list of known hosts.\r\n"
    "Authorized users only. All activity may be monitored and reported.\n"
    'Load key "/tmp/ansible._7oamnkx_ssh_cert": invalid format\r\n'
    "cloudauto@100.66.0.108: Permission denied "
    "(publickey,gssapi-keyex,gssapi-with-mic,password)."
)
SSH_A_JSON = '{"changed": false, "msg": %s, "unreachable": true}' % __import__("json").dumps(SSH_A_MSG)

# --- SSH connect failure, host B (path .../ansible.kgrju_2v_ssh_cert) ---
SSH_B_MSG = (
    "Failed to connect to the host via ssh: Warning: Permanently added "
    "'100.66.0.108' (ED25519) to the list of known hosts.\r\n"
    "Authorized users only. All activity may be monitored and reported.\n"
    'Load key "/tmp/ansible.kgrju_2v_ssh_cert": invalid format\r\n'
    "cloudauto@100.66.0.108: Permission denied "
    "(publickey,gssapi-keyex,gssapi-with-mic,password)."
)
SSH_B_JSON = '{"changed": false, "msg": %s, "unreachable": true}' % __import__("json").dumps(SSH_B_MSG)

# --- WinRM/NTLM unreachable (parsed_logs.json sample_log) ---
WINRM_JSON = (
    '{"changed": false, "msg": "ntlm: HTTPSConnectionPool(host=\'100.70.7.24\', '
    "port=5986): Max retries exceeded with url: /wsman (Caused by "
    "NewConnectionError('<urllib3.connection.HTTPSConnection object at "
    "0x7fc18f7eaa50>: Failed to establish a new connection: [Errno 113] No route "
    'to host\'))", "unreachable": true}'
)

# --- Day2Actions assert (job_745_events.json runner_on_failed event_data.res) ---
ASSERT_JSON = (
    '{"_ansible_verbose_always": true, "evaluated_to": false, "assertion": '
    '"(resources.count | default(0)) > 0", "msg": "Resource '
    "'d2a-throwaway-del' not found in CDB for organization 'acmeco'\", "
    '"_ansible_no_log": false, "changed": false}'
)
