"""Tests for runtime-hardening constants + the bedrock_model_kwargs() helper."""

import constants


def test_timeout_and_iteration_caps_present():
    assert constants.TICK_TIMEOUT_SECONDS == 3.5
    assert constants.MAX_TOOL_ITERATIONS == 2
    assert constants.PER_TOOL_TIMEOUT_SECONDS == 1.0


def test_bedrock_model_kwargs_disables_retries(monkeypatch):
    monkeypatch.delenv("BEDROCK_GUARDRAIL_ID", raising=False)
    monkeypatch.delenv("BEDROCK_GUARDRAIL_VERSION", raising=False)

    kwargs = constants.bedrock_model_kwargs()

    assert kwargs["model_id"] == constants.MODEL_ID
    cfg = kwargs["boto_client_config"]
    # botocore Config exposes retries as a plain dict.
    assert cfg.retries["max_attempts"] == 1
    assert cfg.retries["mode"] == "standard"


def test_bedrock_model_kwargs_no_guardrail_keys_when_unset(monkeypatch):
    monkeypatch.delenv("BEDROCK_GUARDRAIL_ID", raising=False)
    monkeypatch.delenv("BEDROCK_GUARDRAIL_VERSION", raising=False)

    kwargs = constants.bedrock_model_kwargs()

    assert "guardrail_id" not in kwargs
    assert "guardrail_version" not in kwargs


def test_bedrock_model_kwargs_includes_guardrail_when_set(monkeypatch):
    monkeypatch.setenv("BEDROCK_GUARDRAIL_ID", "gr-123")
    monkeypatch.delenv("BEDROCK_GUARDRAIL_VERSION", raising=False)

    kwargs = constants.bedrock_model_kwargs()

    assert kwargs["guardrail_id"] == "gr-123"
    # Defaults to DRAFT when the version env var is unset.
    assert kwargs["guardrail_version"] == "DRAFT"


def test_bedrock_model_kwargs_honors_guardrail_version(monkeypatch):
    monkeypatch.setenv("BEDROCK_GUARDRAIL_ID", "gr-123")
    monkeypatch.setenv("BEDROCK_GUARDRAIL_VERSION", "3")

    kwargs = constants.bedrock_model_kwargs()

    assert kwargs["guardrail_version"] == "3"
