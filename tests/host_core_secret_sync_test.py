from __future__ import annotations

import base64
import json
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from wechat_airflow.host_core import secret_sync


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self.payload


def test_migration_token_prefers_explicit_environment() -> None:
    with (
        patch.dict("os.environ", {"AIRFLOW_PUSH_TOKEN": "environment-token"}),
        patch.object(secret_sync, "_airflow_variable") as variable,
    ):
        assert secret_sync._migration_token() == "environment-token"
    variable.assert_not_called()


def test_migration_token_falls_back_to_existing_airflow_variable() -> None:
    with (
        patch.dict("os.environ", {}, clear=True),
        patch.object(
            secret_sync,
            "_airflow_variable",
            return_value="airflow-variable-token",
        ) as variable,
    ):
        assert secret_sync._migration_token() == "airflow-variable-token"
    variable.assert_called_once_with("WEBAPP_OBSERVATION_API_TOKEN")


def test_secret_bundle_is_hybrid_encrypted_and_installed_without_plaintext_transport(
    tmp_path: Path,
) -> None:
    expected = {
        "tencent_secret_id": "id-value",
        "tencent_secret_key": "key-value",
        "tencent_region": "ap-guangzhou",
        "email_from_address": "sender@example.com",
        "email_reply_to": "reply@example.com",
        "email_template_id": "12345",
    }

    def post(url: str, **kwargs: object) -> _Response:
        assert url.endswith("/api/internal/host-secret-envelope")
        body = kwargs["json"]
        assert isinstance(body, dict)
        encoded_key = str(body["publicKeySpki"])
        public_der = base64.urlsafe_b64decode(encoded_key + "=" * ((4 - len(encoded_key) % 4) % 4))
        public_key = serialization.load_der_public_key(public_der)
        aes_key = AESGCM.generate_key(bit_length=256)
        iv = b"0123456789ab"
        ciphertext = AESGCM(aes_key).encrypt(
            iv,
            json.dumps(expected, separators=(",", ":")).encode(),
            None,
        )
        encrypted_key = public_key.encrypt(
            aes_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        return _Response(
            {
                "algorithm": "RSA-OAEP-256+A256GCM",
                "encryptedKey": _encode(encrypted_key),
                "iv": _encode(iv),
                "ciphertext": _encode(ciphertext),
            }
        )

    with patch.object(secret_sync.requests, "post", side_effect=post):
        bundle = secret_sync.request_secret_bundle("https://example.test", "migration-token")

    assert bundle == expected
    assert secret_sync.install_secret_bundle(tmp_path, bundle) == 6
    for key, filename in secret_sync.SECRET_FILENAMES.items():
        path = tmp_path / filename
        assert path.read_text(encoding="utf-8").strip() == expected[key]
        assert path.stat().st_mode & 0o777 == 0o640
