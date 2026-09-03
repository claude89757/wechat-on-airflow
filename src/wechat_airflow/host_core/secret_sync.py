from __future__ import annotations

import argparse
import base64
import json
import os
import tempfile
from pathlib import Path

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SECRET_FILENAMES = {
    "tencent_secret_id": "tencent_secret_id",
    "tencent_secret_key": "tencent_secret_key",
    "tencent_region": "tencent_region",
    "email_from_address": "email_from_address",
    "email_reply_to": "email_reply_to",
    "email_template_id": "email_template_id",
}


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * ((4 - len(value) % 4) % 4))


def _airflow_variable(name: str) -> str | None:
    try:
        from airflow.sdk import Variable as SdkVariable

        value = SdkVariable.get(name, default=None)
    except Exception:
        try:
            from airflow.models.variable import Variable as ModelVariable

            value = ModelVariable.get(name, default_var=None)
        except Exception:
            return None
    normalized = str(value or "").strip()
    return normalized or None


def _migration_token() -> str:
    token = os.environ.get("AIRFLOW_PUSH_TOKEN", "").strip()
    if not token:
        token = _airflow_variable("WEBAPP_OBSERVATION_API_TOKEN") or ""
    if not token:
        raise RuntimeError(
            "AIRFLOW_PUSH_TOKEN or WEBAPP_OBSERVATION_API_TOKEN is required for secret migration"
        )
    return token


def request_secret_bundle(base_url: str, token: str) -> dict[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    public_der = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    response = requests.post(
        f"{base_url.rstrip('/')}/api/internal/host-secret-envelope",
        json={"publicKeySpki": _encode(public_der)},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    response.raise_for_status()
    envelope = response.json()
    if not isinstance(envelope, dict):
        raise RuntimeError("secret migration returned an invalid envelope")
    if envelope.get("algorithm") != "RSA-OAEP-256+A256GCM":
        raise RuntimeError("secret migration returned an unsupported algorithm")
    try:
        encrypted_key = _decode(str(envelope["encryptedKey"]))
        iv = _decode(str(envelope["iv"]))
        ciphertext = _decode(str(envelope["ciphertext"]))
    except (KeyError, ValueError) as exc:
        raise RuntimeError("secret migration returned an incomplete envelope") from exc
    aes_key = private_key.decrypt(
        encrypted_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    plaintext = AESGCM(aes_key).decrypt(iv, ciphertext, None)
    payload = json.loads(plaintext)
    if not isinstance(payload, dict):
        raise RuntimeError("secret migration returned an invalid bundle")
    result: dict[str, str] = {}
    for key in SECRET_FILENAMES:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"secret bundle is missing {key}")
        result[key] = value.strip()
    return result


def _atomic_secret(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o750)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o640)
        if os.geteuid() == 0:
            os.chown(temporary, 0, 0)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def install_secret_bundle(secret_dir: Path, bundle: dict[str, str]) -> int:
    for key, filename in SECRET_FILENAMES.items():
        _atomic_secret(secret_dir / filename, bundle[key])
    return len(SECRET_FILENAMES)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Transfer Cloudflare runtime mail secrets to the Airflow host"
    )
    parser.add_argument("--base-url", default="https://zacks.claude89757.cc")
    parser.add_argument(
        "--secret-dir",
        type=Path,
        default=Path(os.environ.get("ZACKS_SECRET_DIR", "/etc/wechat-on-airflow/secrets")),
    )
    arguments = parser.parse_args()
    bundle = request_secret_bundle(arguments.base_url, _migration_token())
    installed = install_secret_bundle(arguments.secret_dir, bundle)
    print(json.dumps({"success": True, "installed": installed}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
