from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, cast

import requests
from cryptography.hazmat.primitives import padding, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asymmetric_padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

DEFAULT_BASE_URL = "https://nswtt.rim20.com/api/"
DEFAULT_PROJECT_ID = "1f2c23a3-3720-44c8-b78b-971d8860fbac"
FREE_PAY_TYPE = 1
RANDOM_ALPHABET = "ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678"
ZERO_IV = b"0000000000000000"
RSA_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAwNlbrRQpIHlTNfjSrBJQ
oI5t1aRTAbDy61fJPJLFfhacW1jfmLJpONm1wxFmhKcIt8WVyTQKdAD2HdUrBuoz
75LDY4Lm3k4+9hZrftAnE6hnuPCj7E34wgP5riZ6DfK9PYeSJDvZ4wXvpw0m2e84
MlpaJD85BcCXTfTZctKXz/cQhFcgilMF93Q79OesAdd/qHQIbl4/TuYa40HClKnl
zNTIIw+LtrYqn3STGxJhrCuu0UGNznznv4VmFtFtmww5nu16vV0z9tUZIsQyJze
K+Re/C+y7Do962rzuzLb7DqYwLo7VBqO5P3abhr4JliS1eFv314SSj9cvmVsu3Ku
noQIDAQAB
-----END PUBLIC KEY-----"""


class NswttApiError(RuntimeError):
    pass


class NswttAuthExpired(NswttApiError):
    pass


@dataclass(frozen=True)
class NswttConfig:
    app_version: str
    cookie: str
    page_path: str = ""
    page_uuid: str = ""
    base_url: str = DEFAULT_BASE_URL
    project_id: str = DEFAULT_PROJECT_ID
    timeout_seconds: float = 15.0

    @classmethod
    def from_value(cls, value: object) -> NswttConfig:
        if not isinstance(value, dict):
            raise ValueError("NSWTT_API_CONFIG must be a JSON object")
        raw = cast(dict[str, object], value)
        cookie_value = raw.get("cookie")
        if isinstance(cookie_value, dict):
            cookie = "; ".join(
                f"{key}={item}" for key, item in cookie_value.items() if str(key) and str(item)
            )
        else:
            cookie = str(cookie_value or "").strip()
        app_version = str(raw.get("app_version") or "").strip()
        if not app_version or not cookie:
            raise ValueError("NSWTT_API_CONFIG requires app_version and cookie")
        base_url = str(raw.get("base_url") or DEFAULT_BASE_URL).strip()
        project_id = str(raw.get("project_id") or DEFAULT_PROJECT_ID).strip()
        timeout_seconds = float(str(raw.get("timeout_seconds") or 15.0))
        if not base_url.startswith("https://") or not project_id:
            raise ValueError("NSWTT_API_CONFIG contains an invalid endpoint or project_id")
        return cls(
            app_version=app_version,
            cookie=cookie,
            page_path=str(raw.get("page_path") or "").strip(),
            page_uuid=str(raw.get("page_uuid") or "").strip(),
            base_url=f"{base_url.rstrip('/')}/",
            project_id=project_id,
            timeout_seconds=min(max(timeout_seconds, 1.0), 30.0),
        )


@dataclass(frozen=True)
class EncodedPayload:
    key: str
    timestamp: int
    headers: dict[str, str]

    def decrypt(self, ciphertext: str) -> str:
        encrypted = base64.b64decode(ciphertext)
        decryptor = Cipher(algorithms.AES(self.key.encode()), modes.CBC(ZERO_IV)).decryptor()
        padded = decryptor.update(encrypted) + decryptor.finalize()
        unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
        return (unpadder.update(padded) + unpadder.finalize()).decode()


def encode_payload(
    plain_text: str,
    *,
    key: str | None = None,
    timestamp: int | None = None,
) -> EncodedPayload:
    aes_key = key or "".join(secrets.choice(RANDOM_ALPHABET) for _ in range(32))
    if len(aes_key.encode()) != 32:
        raise ValueError("NSWTT AES key must contain 32 bytes")
    request_timestamp = timestamp or int(time.time() * 1000)
    public_key = serialization.load_pem_public_key(RSA_PUBLIC_KEY.encode())
    rsa_key = cast(RSAPublicKey, public_key)
    encrypted_key = rsa_key.encrypt(aes_key.encode(), asymmetric_padding.PKCS1v15())
    plain_base64 = base64.b64encode(plain_text.encode()).decode()
    signature = hashlib.md5(  # noqa: S324 - required by the upstream protocol
        f"{request_timestamp}@{aes_key}@{plain_base64}".encode()
    ).hexdigest()
    return EncodedPayload(
        key=aes_key,
        timestamp=request_timestamp,
        headers={
            "X-APP-SN": base64.b64encode(encrypted_key).decode(),
            "X-APP-SIGN": signature,
            "X-APP-TIMESTAMP": str(request_timestamp),
        },
    )


class NswttClient:
    def __init__(self, config: NswttConfig, session: requests.Session | None = None) -> None:
        self.config = config
        self.session = session or requests.Session()

    def _get(self, endpoint: str, params: dict[str, str | int]) -> dict[str, Any]:
        clean_params = {key: value for key, value in params.items() if value is not None}
        plain_text = "&".join(f"{key}={value}" for key, value in sorted(clean_params.items()))
        encoded = encode_payload(plain_text)
        headers = {
            "app-version": self.config.app_version,
            "content-type": "application/json; charset=utf-8",
            "cookie": self.config.cookie,
            **encoded.headers,
        }
        if self.config.page_path:
            headers["x-page-path"] = self.config.page_path
        if self.config.page_uuid:
            headers["x-page-uuid"] = self.config.page_uuid
        response = self.session.get(
            f"{self.config.base_url}{endpoint}",
            params=clean_params,
            headers=headers,
            timeout=self.config.timeout_seconds,
        )
        try:
            payload = response.json()
        except requests.JSONDecodeError as exc:
            raise NswttApiError(f"NSWTT returned non-JSON HTTP {response.status_code}") from exc
        if not isinstance(payload, dict):
            raise NswttApiError("NSWTT returned an invalid response")
        if payload.get("data_encode"):
            try:
                payload["data"] = json.loads(encoded.decrypt(str(payload["data_encode"])))
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                raise NswttApiError("NSWTT encrypted response could not be decoded") from exc
        code = payload.get("code")
        message = str(payload.get("msg") or "")
        if (
            response.status_code == 403
            or code in {100000, 100003}
            or any(marker in message for marker in ("用户未登录", "登录超时"))
        ):
            raise NswttAuthExpired("NSWTT authentication has expired")
        if not response.ok:
            raise NswttApiError(f"NSWTT returned HTTP {response.status_code}")
        if code != 0:
            raise NswttApiError(f"NSWTT API error code {code}")
        return cast(dict[str, Any], payload)

    def calendar_list(self) -> dict[str, Any]:
        return self._get(
            "wtt/sport/calendar/list",
            {"projectid": self.config.project_id, "paytype": FREE_PAY_TYPE},
        )

    def slice_list(self, booking_date: str) -> dict[str, Any]:
        return self._get(
            "wtt/sport/slice/list",
            {
                "scene": "11",
                "slicedate": booking_date,
                "projectid": self.config.project_id,
                "paytype": FREE_PAY_TYPE,
            },
        )
