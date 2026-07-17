from __future__ import annotations

import json
import logging
import os
from typing import Any

from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.ses.v20201002 import models, ses_client

LOGGER = logging.getLogger(__name__)


def _runtime_secret(variable_name: str, explicit_value: str | None) -> str:
    if explicit_value:
        return explicit_value

    try:
        from airflow.sdk import Variable

        value = Variable.get(variable_name, default_var="")
    except Exception:
        value = os.environ.get(variable_name, "")

    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{variable_name} is not configured")
    return normalized


class TencentSESClient:
    """Minimal Tencent SES template-email client."""

    def __init__(
        self,
        secret_id: str | None = None,
        secret_key: str | None = None,
        endpoint: str = "ses.tencentcloudapi.com",
        region: str = "ap-guangzhou",
    ) -> None:
        self.secret_id = _runtime_secret("TENCENT_CLOUD_SECRET_ID", secret_id)
        self.secret_key = _runtime_secret("TENCENT_CLOUD_SECRET_KEY", secret_key)
        self.endpoint = endpoint
        self.region = region
        self.client = self._init_client()

    def _init_client(self) -> Any:
        credentials = credential.Credential(self.secret_id, self.secret_key)
        http_profile = HttpProfile()
        http_profile.endpoint = self.endpoint
        client_profile = ClientProfile()
        client_profile.httpProfile = http_profile
        return ses_client.SesClient(credentials, self.region, client_profile)

    def send_template_email(
        self,
        subject: str,
        template_id: int,
        template_data: dict[str, object],
        recipients: list[str],
        from_email: str,
        reply_to: str | None = None,
        cc_emails: list[str] | None = None,
        bcc_emails: list[str] | None = None,
        trigger_type: int = 1,
    ) -> dict[str, object]:
        if not recipients:
            raise ValueError("recipients must not be empty")
        if len(recipients) > 50:
            raise ValueError("recipients must contain at most 50 addresses")
        if cc_emails and len(cc_emails) > 20:
            raise ValueError("cc_emails must contain at most 20 addresses")
        if bcc_emails and len(bcc_emails) > 20:
            raise ValueError("bcc_emails must contain at most 20 addresses")

        request = models.SendEmailRequest()
        params: dict[str, object] = {
            "FromEmailAddress": from_email,
            "Destination": recipients,
            "Subject": subject,
            "Template": {
                "TemplateID": template_id,
                "TemplateData": json.dumps(template_data, ensure_ascii=False),
            },
            "TriggerType": trigger_type,
        }
        if reply_to:
            params["ReplyToAddresses"] = reply_to
        if cc_emails:
            params["Cc"] = cc_emails
        if bcc_emails:
            params["Bcc"] = bcc_emails

        try:
            request.from_json_string(json.dumps(params))
            response = self.client.SendEmail(request)
            response_data: dict[str, object] = json.loads(response.to_json_string())
            LOGGER.info(
                "tencent_ses_sent message_id_present=%s",
                bool(response_data.get("MessageId")),
            )
            return {
                "success": True,
                "message_id": response_data.get("MessageId"),
                "request_id": response_data.get("RequestId"),
                "error": None,
            }
        except TencentCloudSDKException as exc:
            error = f"{exc.code}: {exc.message}"
            LOGGER.error("tencent_ses_failed error=%s", error)
            return {
                "success": False,
                "message_id": None,
                "request_id": None,
                "error": error,
            }
        except Exception as exc:
            LOGGER.exception("tencent_ses_unexpected_failure")
            return {
                "success": False,
                "message_id": None,
                "request_id": None,
                "error": str(exc),
            }


def send_template_email(
    subject: str,
    template_id: int,
    template_data: dict[str, object],
    recipients: list[str],
    from_email: str,
    reply_to: str | None = None,
    cc_emails: list[str] | None = None,
    bcc_emails: list[str] | None = None,
    trigger_type: int = 1,
) -> dict[str, object]:
    return TencentSESClient().send_template_email(
        subject=subject,
        template_id=template_id,
        template_data=template_data,
        recipients=recipients,
        from_email=from_email,
        reply_to=reply_to,
        cc_emails=cc_emails,
        bcc_emails=bcc_emails,
        trigger_type=trigger_type,
    )
