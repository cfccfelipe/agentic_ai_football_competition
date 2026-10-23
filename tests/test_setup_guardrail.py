"""Tests for the conditional, OWN-code Bedrock Guardrail helper.

The guardrail is created OUTSIDE the vended CDK project (which is off-limits):
a small boto3-backed helper creates/updates a content-safety guardrail ONLY
when CREATE_BEDROCK_GUARDRAIL is set, and reports its id + version so they can
be provided to the runtimes as BEDROCK_GUARDRAIL_ID / BEDROCK_GUARDRAIL_VERSION.

All tests are pure: the boto3 client is faked and injected — no AWS, no network.
"""

import pytest

import setup_guardrail


class _FakeBedrockClient:
    """Records create_guardrail / create_guardrail_version calls, returns ids."""

    def __init__(self):
        self.create_calls = []
        self.version_calls = []

    def create_guardrail(self, **kwargs):
        self.create_calls.append(kwargs)
        return {"guardrailId": "gr-fake-123", "guardrailArn": "arn:aws:...:gr-fake-123"}

    def create_guardrail_version(self, **kwargs):
        self.version_calls.append(kwargs)
        return {"guardrailId": kwargs.get("guardrailIdentifier"), "version": "1"}


# --- build_guardrail_config: pure content-safety policy -------------------

def test_config_has_required_scalar_fields():
    cfg = setup_guardrail.build_guardrail_config()
    assert cfg["name"]
    assert cfg["blockedInputMessaging"]
    assert cfg["blockedOutputsMessaging"]


def test_config_content_filters_cover_all_categories_at_medium():
    cfg = setup_guardrail.build_guardrail_config()
    filters = cfg["contentPolicyConfig"]["filtersConfig"]
    by_type = {f["type"]: f for f in filters}
    for cat in ("HATE", "INSULTS", "SEXUAL", "VIOLENCE", "MISCONDUCT"):
        assert cat in by_type
        assert by_type[cat]["inputStrength"] == "MEDIUM"
        assert by_type[cat]["outputStrength"] == "MEDIUM"
    # Prompt-attack is input-only at HIGH (no output strength for this category).
    assert "PROMPT_ATTACK" in by_type
    assert by_type["PROMPT_ATTACK"]["inputStrength"] == "HIGH"
    assert by_type["PROMPT_ATTACK"]["outputStrength"] == "NONE"


def test_config_denies_one_off_domain_role_override_topic():
    cfg = setup_guardrail.build_guardrail_config()
    topics = cfg["topicPolicyConfig"]["topicsConfig"]
    assert len(topics) == 1
    topic = topics[0]
    assert topic["type"] == "DENY"
    assert topic["name"]
    assert topic["definition"]


# --- ensure_guardrail: gated on the env flag, injected client -------------

def test_disabled_by_default_makes_no_calls(monkeypatch):
    monkeypatch.delenv("CREATE_BEDROCK_GUARDRAIL", raising=False)
    client = _FakeBedrockClient()

    result = setup_guardrail.ensure_guardrail(client=client)

    assert result is None
    assert client.create_calls == []
    assert client.version_calls == []


def test_enabled_creates_guardrail_and_version(monkeypatch):
    monkeypatch.setenv("CREATE_BEDROCK_GUARDRAIL", "true")
    client = _FakeBedrockClient()

    result = setup_guardrail.ensure_guardrail(client=client)

    assert result == ("gr-fake-123", "1")
    assert len(client.create_calls) == 1
    # The create call carries the content-safety policy.
    sent = client.create_calls[0]
    assert sent["name"]
    assert "contentPolicyConfig" in sent
    # A version is published off the created guardrail id.
    assert len(client.version_calls) == 1
    assert client.version_calls[0]["guardrailIdentifier"] == "gr-fake-123"


def test_enabled_but_falsey_flag_makes_no_calls(monkeypatch):
    monkeypatch.setenv("CREATE_BEDROCK_GUARDRAIL", "false")
    client = _FakeBedrockClient()

    assert setup_guardrail.ensure_guardrail(client=client) is None
    assert client.create_calls == []
