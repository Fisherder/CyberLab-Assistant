from __future__ import annotations

from cla.settings import load_settings


def test_load_settings_maps_production_oidc_environment(monkeypatch) -> None:
    monkeypatch.setenv("CLA_DEV_MODE", "false")
    monkeypatch.setenv("CLA_OIDC_ISSUER", "https://issuer.example.edu")
    monkeypatch.setenv("CLA_OIDC_AUDIENCE", "cla-api")
    monkeypatch.setenv("CLA_OIDC_JWKS_URL", "https://issuer.example.edu/jwks")
    monkeypatch.setenv(
        "CLA_OIDC_DISCOVERY_URL",
        "https://issuer.example.edu/.well-known/openid-configuration",
    )
    monkeypatch.setenv("CLA_OIDC_JWKS_JSON", '{"keys":[]}')
    monkeypatch.setenv("CLA_OIDC_ALGORITHMS", "RS256,ES256")
    monkeypatch.setenv("CLA_TRANSCRIPT_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("CLA_TRANSCRIPT_S3_BUCKET", "cla-transcript-raw")
    monkeypatch.setenv("CLA_TRANSCRIPT_S3_PREFIX", "raw/terminal")
    monkeypatch.setenv("CLA_TRANSCRIPT_S3_ENDPOINT_URL", "http://minio:9000")
    monkeypatch.setenv("CLA_TRANSCRIPT_S3_REGION", "us-west-2")
    monkeypatch.setenv("CLA_TRANSCRIPT_S3_FORCE_PATH_STYLE", "true")

    settings = load_settings()

    assert settings.dev_mode is False
    assert settings.oidc_issuer == "https://issuer.example.edu"
    assert settings.oidc_audience == "cla-api"
    assert settings.oidc_jwks_url == "https://issuer.example.edu/jwks"
    assert (
        settings.oidc_discovery_url
        == "https://issuer.example.edu/.well-known/openid-configuration"
    )
    assert settings.oidc_jwks_json == '{"keys":[]}'
    assert settings.oidc_algorithms == ("RS256", "ES256")
    assert settings.transcript_storage_backend == "s3"
    assert settings.transcript_s3_bucket == "cla-transcript-raw"
    assert settings.transcript_s3_prefix == "raw/terminal"
    assert settings.transcript_s3_endpoint_url == "http://minio:9000"
    assert settings.transcript_s3_region == "us-west-2"
    assert settings.transcript_s3_force_path_style is True
