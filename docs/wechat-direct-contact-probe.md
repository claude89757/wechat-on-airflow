# Direct WeChat Contact Probe

This runbook provides a bounded, auditable way to send one real acceptance
message to one explicitly selected WeChat contact through the production
`wechat-on-airflow` sender.

## Safety contract

- A real send requires an explicit owner command and the existing
  `confirm_real_send` gate.
- The command is accepted only on issue `#39` and only from the repository
  owner.
- The target commit must be a full 40-character commit on `main`, and its
  authoritative `CI / verify` check must pass.
- The message body is hard-coded by `scripts/probe_wechat_delivery.py`.
  Operators cannot inject arbitrary message content.
- Direct mode does not load configured group-chat Variables.
- Structured output redacts the contact name and message body.
- The operation does not mutate Airflow Variables or replay the WeChat fallback
  outbox.

## Command

Post this exact command as the repository owner on issue `#39`:

```text
/ops wechat-contact-probe <40-character-main-commit> <simple-chat-name>
```

For the contact `Tt`:

```text
/ops wechat-contact-probe <40-character-main-commit> Tt
```

The ChatOps workflow invokes the protected `production` Environment and reuses
the existing `wechat_delivery_probe` operation with a `direct:<chat-name>`
selector. One message is sent:

```text
【系统验收】微信发送链路测试，发送时间：<UTC timestamp>。无需回复。
```

A successful result reports one target, one successful send, and the sender
navigation path without returning the receiver or message content.

## Failure handling

- `contact_not_found` or title-verification errors mean the visible WeChat
  contact name did not exactly match the requested name.
- `device_not_ready`, `appium_timeout`, and `device_busy` are sender/device
  incidents. Diagnose them with the protected sender and delivery diagnostics.
- Do not manually replay an ambiguous request. The production sender and Airflow
  client already provide bounded retries and idempotency behavior.
