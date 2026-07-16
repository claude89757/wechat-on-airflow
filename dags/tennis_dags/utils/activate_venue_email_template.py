#!/usr/bin/env python3

import sys


TARGET_TEMPLATE_ID = 54297
TEMPLATE_ID_VARIABLE = "VENUE_EMAIL_TEMPLATE_ID"
APPROVED = 0
PENDING = 1
REJECTED = 2


def activate_if_approved() -> int:
    from airflow.models import Variable
    from tencentcloud.ses.v20201002 import models

    from tennis_dags.utils.tencent_ses import TencentSESClient

    current_template_id = int(
        Variable.get(TEMPLATE_ID_VARIABLE, default_var="33340")
    )
    if current_template_id == TARGET_TEMPLATE_ID:
        print(f"{TEMPLATE_ID_VARIABLE} already active: {TARGET_TEMPLATE_ID}")
        return 0

    client = TencentSESClient()
    request = models.GetEmailTemplateRequest()
    request.TemplateID = TARGET_TEMPLATE_ID
    response = client.client.GetEmailTemplate(request)

    if response.TemplateStatus == APPROVED:
        Variable.set(
            TEMPLATE_ID_VARIABLE,
            str(TARGET_TEMPLATE_ID),
            description="Approved concise venue email template",
        )
        print(f"{TEMPLATE_ID_VARIABLE} activated: {TARGET_TEMPLATE_ID}")
        return 0
    if response.TemplateStatus == PENDING:
        print(f"template {TARGET_TEMPLATE_ID} is pending review")
        return 75
    if response.TemplateStatus == REJECTED:
        print(f"template {TARGET_TEMPLATE_ID} was rejected")
        return 2

    print(f"template {TARGET_TEMPLATE_ID} has unknown status: {response.TemplateStatus}")
    return 1


if __name__ == "__main__":
    sys.exit(activate_if_approved())
