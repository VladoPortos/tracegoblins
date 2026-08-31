from app.kb.signature import Signature, extract_signature


def test_signature_is_frozen_dataclass():
    sig = Signature(signature_key="k", representative_text="t", category="c")
    assert sig.signature_key == "k"
    assert sig.representative_text == "t"
    assert sig.category == "c"


def test_blank_and_none_return_none():
    assert extract_signature(None) is None
    assert extract_signature("") is None
    assert extract_signature("   ") is None


def test_returns_a_signature_for_a_plain_message():
    sig = extract_signature("something went wrong here")
    assert isinstance(sig, Signature)
    assert sig.representative_text == "something went wrong here"


def test_dict_with_no_message_keys_falls_back_to_dumps_not_none():
    # {"changed": false} -> no msg/module_stderr/stderr/exception/reason -> json.dumps
    # is '{"changed": false}', which is non-blank, so it is NOT None (it classifies in B4).
    sig = extract_signature('{"changed": false}')
    assert sig is not None
    assert "changed" in sig.representative_text  # the serialized dict text survives


def test_empty_object_is_not_none():
    # json.dumps({}) == "{}" which is non-blank -> not None.
    sig = extract_signature("{}")
    assert sig is not None


def test_message_key_priority_order():
    # msg wins over module_stderr/stderr/exception/reason.
    sig = extract_signature(
        '{"msg": "primary", "module_stderr": "secondary", "stderr": "tertiary"}'
    )
    assert sig is not None
    assert "primary" in sig.representative_text
    assert "secondary" not in sig.representative_text


def test_module_stderr_used_when_msg_absent_or_blank():
    sig = extract_signature('{"msg": "   ", "module_stderr": "real failure detail"}')
    assert sig is not None
    assert "real failure detail" in sig.representative_text


def test_non_json_garbage_is_used_as_raw_message():
    sig = extract_signature("this is not json at all >>> %%%")
    assert sig is not None
    assert "not json" in sig.representative_text


def test_json_string_scalar_uses_raw_text():
    # json.loads('"hi"') -> 'hi' (a str, not a dict) -> our code uses the RAW error_text.
    sig = extract_signature('"hi there"')
    assert sig is not None
    assert sig.representative_text  # non-empty; raw '"hi there"' is used


from tests.kb import fixtures as f


def test_classify_ssh_connection_both_shapes():
    for blob in (f.SSH_A_JSON, f.SSH_B_JSON, f.SSH_A_MSG, f.SSH_B_MSG):
        sig = extract_signature(blob)
        assert sig is not None
        assert sig.signature_key == "ssh_connection_failed"
        assert sig.category == "connectivity"


def test_classify_winrm_connection():
    sig = extract_signature(f.WINRM_JSON)
    assert sig is not None
    assert sig.signature_key == "winrm_connection_failed"
    assert sig.category == "connectivity"


def test_classify_assertion_via_raw_json_fallback():
    # The chosen msg ("Resource '...' not found...") has NO 'assert' token; Step 2b
    # must scan the raw error_text (which has "assertion" + "evaluated_to": false).
    sig = extract_signature(f.ASSERT_JSON)
    assert sig is not None
    assert sig.signature_key == "assertion_failed"
    assert sig.category == "precondition"


def test_ssh_connect_wins_over_ssh_auth_ordering():
    # The real SSH blob ALSO contains "Permission denied (publickey" and
    # "Load key ... invalid format" (ssh_auth_failed patterns). Connect (1) is first.
    sig = extract_signature(f.SSH_A_MSG)
    assert sig is not None
    assert sig.signature_key == "ssh_connection_failed"  # NOT ssh_auth_failed


def test_pattern_ssh_auth_when_no_connect_prefix():
    sig = extract_signature("Host key verification failed.")
    assert sig is not None
    assert sig.signature_key == "ssh_auth_failed"
    assert sig.category == "auth"


def test_pattern_connection_timeout():
    sig = extract_signature(
        '{"msg": "Failed to connect: connection timed out after 30s"}'
    )
    assert sig is not None
    assert sig.signature_key == "connection_timeout"
    assert sig.category == "connectivity"


def test_pattern_assertion_plain_message():
    sig = extract_signature('{"msg": "Assertion failed: value must be > 0"}')
    assert sig is not None
    assert sig.signature_key == "assertion_failed"
    assert sig.category == "precondition"


def test_pattern_package_not_found():
    sig = extract_signature('{"msg": "No package matching docker-ce is available"}')
    assert sig is not None
    assert sig.signature_key == "package_not_found"
    assert sig.category == "package"


def test_pattern_permission_denied():
    sig = extract_signature('{"msg": "Permission denied: /etc/shadow"}')
    assert sig is not None
    assert sig.signature_key == "permission_denied"
    assert sig.category == "permission"


def test_generic_fallback_key_and_slug():
    sig = extract_signature("totally unrecognized widget exploded sideways")
    assert sig is not None
    assert sig.signature_key.startswith("generic:")
    assert sig.category is None
    # slug: lowercase, non-[a-z0-9] -> '-', trimmed, <=60 chars after the prefix
    slug = sig.signature_key[len("generic:"):]
    assert slug == slug.lower()
    assert not slug.startswith("-") and not slug.endswith("-")
    assert len(slug) <= 60


def test_generic_slug_is_stable_for_same_text():
    a = extract_signature("widget exploded code 9 at node alpha")
    b = extract_signature("widget exploded code 9 at node alpha")
    assert a is not None and b is not None
    assert a.signature_key == b.signature_key


# --- B5: host-strip → representative_text (the load-bearing SSH collapse golden) ---

def test_two_ssh_hosts_collapse_to_identical_representative_text():
    # THE load-bearing golden (Contract §0 #1/#2): same key AND identical
    # representative_text for host A vs host B, which differ ONLY in the
    # /tmp/ansible.<rand>_ssh_cert path. Holds for both storage shapes.
    a_json = extract_signature(f.SSH_A_JSON)
    b_json = extract_signature(f.SSH_B_JSON)
    a_msg = extract_signature(f.SSH_A_MSG)
    b_msg = extract_signature(f.SSH_B_MSG)
    assert a_json is not None and b_json is not None
    assert a_msg is not None and b_msg is not None
    assert a_json.signature_key == b_json.signature_key == "ssh_connection_failed"
    assert a_json.representative_text == b_json.representative_text
    assert a_msg.representative_text == b_msg.representative_text
    assert a_json.representative_text == a_msg.representative_text  # both shapes agree


def test_ssh_representative_text_strips_host_specifics():
    sig = extract_signature(f.SSH_A_JSON)
    assert sig is not None
    rep = sig.representative_text
    # raw host-specific values are GONE...
    assert "100.66.0.108" not in rep
    assert "_7oamnkx" not in rep
    assert "/tmp/ansible" not in rep
    assert "permanently added" not in rep   # the SSH banner is stripped
    # ...replaced by placeholders, and the text is lowercased + whitespace-collapsed.
    assert "<ip>" in rep
    assert "<path>" in rep
    assert "<ssh-banner>" in rep
    assert rep == rep.lower()
    assert "\n" not in rep and "\r" not in rep
    assert "  " not in rep  # whitespace collapsed to single spaces


def test_winrm_representative_text_strips_ip_and_hex_and_port():
    sig = extract_signature(f.WINRM_JSON)
    assert sig is not None
    rep = sig.representative_text
    # The msg is `... HTTPSConnectionPool(host='100.70.7.24', port=5986): ...`. The IPv4
    # rule (5) turns the IP into <ip> FIRST, then the host=/port= kv-rule (7) re-consumes
    # the whole `host='<ip>',` and `port=5986):` tokens via its trailing \S+ -> they become
    # <host> / <port>. So the final rep carries <host>/<port>/<hex> and NO bare <ip>; the
    # raw host-specific values are all gone.
    assert "100.70.7.24" not in rep      # raw IP stripped (subsumed into <host>)
    assert "5986" not in rep             # raw port stripped (subsumed into <port>)
    assert "0x7fc18f7eaa50" not in rep and "<hex>" in rep
    assert "<host>" in rep               # host=... kv collapsed
    assert "<port>" in rep               # port=... kv collapsed
    assert rep == rep.lower()


def test_assert_representative_text_is_host_stripped_msg_with_names_kept():
    sig = extract_signature(f.ASSERT_JSON)
    assert sig is not None
    rep = sig.representative_text
    # representative_text = the host-stripped MSG (not the raw JSON); the quoted
    # resource/org names are NOT ip/hex/path/uuid/port/ts, so they survive.
    assert "resource" in rep
    assert "d2a-throwaway-del" in rep
    assert "acmeco" in rep
    assert "evaluated_to" not in rep   # came from the raw JSON, not the msg
    assert rep == rep.lower()


def test_host_strip_uuid_and_timestamp_placeholders():
    sig = extract_signature(
        '{"msg": "job 550e8400-e29b-41d4-a716-446655440000 failed at '
        '2026-06-04T12:10:00Z on /var/log/app.log"}'
    )
    assert sig is not None
    rep = sig.representative_text
    assert "550e8400-e29b-41d4-a716-446655440000" not in rep and "<uuid>" in rep
    assert "2026-06-04t12:10:00z" not in rep and "<ts>" in rep
    assert "/var/log/app.log" not in rep and "<path>" in rep


def test_generic_slug_uses_host_stripped_text():
    # The generic key slug is built from the host-stripped representative_text, so two
    # different IPs in otherwise-identical unknown errors yield the SAME generic key.
    a = extract_signature('{"msg": "weird gizmo fault at 10.0.0.1 now"}')
    b = extract_signature('{"msg": "weird gizmo fault at 10.0.0.9 now"}')
    assert a is not None and b is not None
    assert a.signature_key.startswith("generic:")
    assert a.signature_key == b.signature_key
    assert "<ip>" in a.representative_text


# --- B6: graceful-on-garbage hardening ---

import pytest


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "",
        "   ",
        "\n\t  \r\n",
        "{",                       # truncated/invalid JSON -> raw text used
        '{"msg":',                 # invalid JSON -> raw text used
        '{"changed": false, "unreachable": tru',  # the prototype-style truncation
        "[]",                      # JSON list (not dict) -> raw text used
        "42",                      # JSON number scalar -> raw text used
        "null",                    # json.loads -> None (not dict) -> raw 'null' used
        "ÿÿÿ \x00 binary-ish ￿",   # non-ascii / control chars
        "a" * 5000,                # very long input (bounded patterns, no backtracking)
    ],
)
def test_extract_signature_never_raises(bad):
    # Must never raise; returns None (blank) or a Signature (anything non-blank).
    result = extract_signature(bad)
    assert result is None or isinstance(result, Signature)


def test_truncated_prototype_ssh_string_still_classifies_ssh():
    # The literal (truncated, double-escaped) prototype parsed_logs.json SSH string
    # fails json.loads -> we use the RAW text -> the "failed to connect ... via ssh"
    # phrase still classifies. Proves robustness against the prototype artifact.
    proto = (
        '{"changed": false, "msg": "Failed to connect to the host via ssh: '
        "Warning: Permanently added '100.66.0.108' (ED25519) to the list of "
        'known hosts.\\r\\nLoad key \\"/tmp/ansible._7oamnkx_ssh_cert\\": '
        "invalid format\\r\\ncloudauto@100.66.0.108: Permission denied "
        '(publickey).", "unreachable": tru'   # <-- truncated on purpose
    )
    sig = extract_signature(proto)
    assert sig is not None
    assert sig.signature_key == "ssh_connection_failed"


def test_blank_after_unwrap_returns_none():
    # A dict whose only message key is whitespace, with no other keys -> json.dumps is
    # non-blank, so it is NOT None; but a JSON string that is pure whitespace IS blank.
    assert extract_signature('"   "') is not None   # raw '"   "' is non-blank text
    assert extract_signature('   \n  ') is None      # pure-whitespace raw -> None
