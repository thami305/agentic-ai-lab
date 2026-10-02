"""Lab 10 defense unit tests — each defense primitive in isolation.

Covers: audit log append-only + tamper detection, the signed approval
channel (accept/reject, shown-vs-actual), namespace isolation, rate and
spend limits, consent default-deny, output labeling, and schema strictness.
"""
import json

import pytest

from lab10.agent import HardenedAgent, HardenedConfig
from lab10.approvals import (Approval, ApprovalChannel, ApprovalGate,
                             canonical_render)
from lab10.audit import AuditLog
from lab10.cases import TEST_CHANNEL_SECRET, run_case
from lab10.models import ScriptedStub, calls, decline, final_text, tc
from lab10.policy import ConsentStore, NamespaceEnforcer
from lab10.tools import MemoryStore, SideEffectLog, build_registry


def _agent(script, *, role="analyst", namespace="acme", approver=None,
           consent=None, config=None, audit=None, registry=None):
    side_effects = SideEffectLog()
    memory = MemoryStore()
    audit = audit or AuditLog()
    channel = ApprovalChannel(TEST_CHANNEL_SECRET)
    agent = HardenedAgent(
        ScriptedStub(script), registry or build_registry(
            side_effects=side_effects, memory=memory),
        role=role, namespace=namespace, channel=channel,
        approver=approver or (lambda req: channel.issue(req)),
        audit=audit, side_effects=side_effects, memory=memory,
        consent=consent or ConsentStore(),
        config=config or HardenedConfig())
    return agent, side_effects, memory, audit


# ------------------------------------------------------------- audit ---

def test_audit_append_only_and_chain_verifies():
    log = AuditLog()
    log.append("run_started", run_id="r1")
    log.append("denied", run_id="r1", tool="export_client_list",
               reason="role_denied: ...")
    ok, msg = log.verify_chain()
    assert ok, msg
    assert [e["seq"] for e in log.entries()] == [0, 1]
    assert log.entries()[1]["prev_hash"] == log.entries()[0]["hash"]


def test_audit_entries_are_copies():
    log = AuditLog()
    log.append("denied", reason="role_denied")
    log.entries()[0]["reason"] = "tampered in memory"
    ok, _ = log.verify_chain()
    assert ok  # mutating the copy did not touch the log


def test_audit_tamper_detected(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.append("run_started", run_id="r1")
    log.append("approved", run_id="r1", tool="send_notification",
               reason="signed approval verified")
    ok, _ = log.verify_chain()
    assert ok
    # attacker edits the second line on disk
    lines = path.read_text().splitlines()
    entry = json.loads(lines[1])
    entry["reason"] = "forged approval"
    lines[1] = json.dumps(entry)
    path.write_text("\n".join(lines) + "\n")
    ok, msg = AuditLog(path).verify_chain()
    assert not ok, f"tamper went undetected: {msg}"


def test_every_attack_denial_has_a_reason():
    from lab10.cases import CASE_IDS
    for case_id in CASE_IDS:
        _, case = run_case(case_id)
        if case_id == "cascading_failure":
            # this attack ends in a bounded abort, not a policy denial
            aborts = [e for e in case.audit.entries()
                      if e["event"] == "run_aborted"]
            assert aborts and all(a["reason"] for a in aborts), case_id
        else:
            denials = case.audit.denials()
            assert denials, f"{case_id}: no denial in audit log"
            assert all(d["reason"] for d in denials), \
                f"{case_id}: reasonless denial"
        ok, msg = case.audit.verify_chain()
        assert ok, f"{case_id}: {msg}"


# ---------------------------------------------------------- approvals ---

def _req(channel=None):
    channel = channel or ApprovalChannel(TEST_CHANNEL_SECRET)
    return channel.build_request("send_notification",
                                 {"client_id": "acme", "channel": "email",
                                  "message": "hi"})


def test_legit_approval_passes_gate():
    channel = ApprovalChannel(TEST_CHANNEL_SECRET)
    gate = ApprovalGate(channel)
    req = _req(channel)
    ok, reason = gate.verify(channel.issue(req), req)
    assert ok and reason == "approved"


def test_legit_approval_executes_high_impact_tool():
    agent, side_effects, _, audit = _agent(
        [calls(tc("export_client_list",
                  {"client_id": "acme", "format": "csv"})),
         final_text("exported with approval")],
        role="admin")
    result = agent.run("Export the client list.")
    assert result.status == "completed", result.stop_reason
    assert len(side_effects.for_tool("export_client_list")) == 1
    assert any(e["event"] == "approved" for e in audit.entries())


def test_wrong_secret_rejected():
    channel = ApprovalChannel(TEST_CHANNEL_SECRET)
    gate = ApprovalGate(channel)
    req = _req(channel)
    evil = ApprovalChannel(b"attacker-secret")
    ok, reason = gate.verify(evil.issue(req), req)
    assert not ok and reason == "signature_invalid"


def test_tampered_shown_text_rejected():
    channel = ApprovalChannel(TEST_CHANNEL_SECRET)
    gate = ApprovalGate(channel)
    req = _req(channel)
    good = channel.issue(req)
    tampered = Approval(action=good.action, payload_hash=good.payload_hash,
                        shown_text="Send summary to client",
                        signature=good.signature)
    ok, reason = gate.verify(tampered, req)
    # signature was computed over the original shown text -> invalid
    assert not ok and reason == "signature_invalid"


def test_shown_vs_actual_mismatch_rejected_despite_valid_hmac():
    # attack 9 core: valid signature, wrong shown text
    channel = ApprovalChannel(TEST_CHANNEL_SECRET)
    gate = ApprovalGate(channel)
    req = channel.build_request("export_client_list",
                                {"client_id": "acme", "format": "csv"})
    shown = "Send summary to client"
    forged = Approval(action=req.action, payload_hash=req.payload_hash,
                      shown_text=shown,
                      signature=channel.sign(req.action, req.payload_hash,
                                             shown))
    ok, reason = gate.verify(forged, req)
    assert not ok and reason == "shown_text_mismatch"


def test_action_mismatch_rejected():
    channel = ApprovalChannel(TEST_CHANNEL_SECRET)
    gate = ApprovalGate(channel)
    req = _req(channel)
    other = channel.build_request("export_client_list",
                                  {"client_id": "acme", "format": "csv"})
    ok, reason = gate.verify(channel.issue(other), req)
    assert not ok and reason == "action_mismatch"


def test_payload_hash_mismatch_rejected():
    channel = ApprovalChannel(TEST_CHANNEL_SECRET)
    gate = ApprovalGate(channel)
    req = _req(channel)
    approval = channel.issue(req)
    swapped = Approval(action=approval.action,
                       payload_hash="0" * 64,
                       shown_text=approval.shown_text,
                       signature=approval.signature)
    ok, reason = gate.verify(swapped, req)
    assert not ok and reason == "payload_hash_mismatch"


def test_missing_approval_rejected():
    channel = ApprovalChannel(TEST_CHANNEL_SECRET)
    gate = ApprovalGate(channel)
    ok, reason = gate.verify(None, _req(channel))
    assert not ok and reason == "no_approval_presented"


def test_canonical_render_is_deterministic():
    a = canonical_render("export_client_list",
                         {"format": "csv", "client_id": "acme"})
    b = canonical_render("export_client_list",
                         {"client_id": "acme", "format": "csv"})
    assert a == b == 'export_client_list(client_id=\'acme\', format=\'csv\')'


# ---------------------------------------------------------- namespace ---

def test_namespace_enforcer_finds_nested_markers():
    enf = NamespaceEnforcer("acme")
    data = {"ok": True, "rows": [
        {"_ns": "acme", "v": 1},
        {"deep": [{"_ns": "globex", "secret": True}]},
    ]}
    assert enf.violations_in(data) == ["globex"]
    assert enf.violations_in({"_ns": "acme"}) == []


def test_namespace_arg_mismatch_denied_before_execution():
    agent, side_effects, _, audit = _agent(
        [calls(tc("search_docs",
                  {"client_id": "globex", "query": "terms"}))],
        namespace="acme")
    result = agent.run("Show me the contract terms.")
    assert result.status == "denied"
    assert "namespace_violation" in (result.stop_reason or "")
    assert len(side_effects) == 0
    assert any("namespace_violation" in (e["reason"] or "")
               for e in audit.denials())


# ------------------------------------------------------- rate / spend ---

def test_rate_limit_denies_over_limit_run():
    agent, side_effects, _, _ = _agent(
        [calls(tc("update_client_note",
                  {"client_id": "acme", "note": "n1"}),
               tc("update_client_note",
                  {"client_id": "acme", "note": "n2"}),
               tc("update_client_note",
                  {"client_id": "acme", "note": "n3"}))],
        config=HardenedConfig(max_tool_calls=2))
    result = agent.run("Add three notes.")
    assert result.status == "denied"
    assert "rate_limit_exceeded" in (result.stop_reason or "")
    assert len(side_effects.for_tool("update_client_note")) == 2


def test_spend_limit_aborts_before_tools_run():
    agent, side_effects, _, audit = _agent(
        [calls(tc("read_client", {"client_id": "acme"}))],
        config=HardenedConfig(max_tokens=500))  # stub uses 720/turn
    result = agent.run("Who is acme?")
    assert result.status == "aborted"
    assert "spend_limit_exceeded" in (result.stop_reason or "")
    assert len(side_effects) == 0
    assert any("spend_limit_exceeded" in (e["reason"] or "")
               for e in audit.entries() if e["event"] == "run_aborted")


# ------------------------------------------------------------ consent ---

def test_consent_default_deny_then_grant():
    script = [calls(tc("write_memory",
                        {"fact": "Acme renewed.", "scope": "session"})),
              final_text("remembered")]
    consent = ConsentStore()
    assert not consent.granted("memory")
    agent, _, memory, _ = _agent(script, consent=consent)
    result = agent.run("Remember that Acme renewed.")
    assert result.status == "denied"
    assert len(memory) == 0

    consent2 = ConsentStore()
    consent2.grant("memory")
    agent2, _, memory2, _ = _agent(
        [calls(tc("write_memory",
                  {"fact": "Acme renewed.", "scope": "session"})),
         final_text("remembered")], consent=consent2)
    result2 = agent2.run("Remember that Acme renewed.")
    assert result2.status == "completed", result2.stop_reason
    assert len(memory2) == 1


def test_consent_cannot_be_smuggled_in_args():
    agent, _, memory, _ = _agent(
        [calls(tc("write_memory",
                  {"fact": "Acme renewed.", "scope": "session",
                   "consent": True}))])
    result = agent.run("Remember that Acme renewed.")
    assert result.status == "denied"
    assert "invalid_arguments" in (result.stop_reason or "")
    assert len(memory) == 0


# ------------------------------------------------------------ labeling ---

def test_tool_output_labeled_untrusted_data():
    backend_script = [calls(tc("read_client", {"client_id": "acme"})),
                      final_text("acme is enterprise")]
    agent, _, _, _ = _agent(backend_script)
    stub = agent._backend
    result = agent.run("Who is acme?")
    assert result.status == "completed"
    assert stub.observed, "model saw no tool results"
    for obs in stub.observed:
        assert obs.content.startswith("[UNTRUSTED DATA]\n"), obs.content[:60]


def test_decline_path_still_works():
    agent, _, _, _ = _agent([decline("out of scope")])
    result = agent.run("Tell me a joke.")
    assert result.status == "declined"
    assert result.decline is not None


def test_schema_rejects_path_traversal_directly():
    from pydantic import ValidationError
    from lab10.schemas import ReadClientArgs
    with pytest.raises(ValidationError):
        ReadClientArgs(client_id="../../../etc/passwd")
    with pytest.raises(ValidationError):
        ReadClientArgs(client_id="ACME")  # uppercase not a slug
    assert ReadClientArgs(client_id="acme-01").client_id == "acme-01"
