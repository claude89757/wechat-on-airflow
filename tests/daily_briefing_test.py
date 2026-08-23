from __future__ import annotations

import datetime
import unittest.mock
import zoneinfo

import pytest
from wechat_airflow.briefings import daily_briefing, openai_client


LOCAL_TIME = datetime.datetime(
    2026,
    8,
    24,
    9,
    0,
    tzinfo=zoneinfo.ZoneInfo("Asia/Shanghai"),
)


def test_build_prompt_contains_exact_window_and_priorities() -> None:
    prompt = daily_briefing.build_briefing_prompt(
        now=LOCAL_TIME,
        topics=["AI", "韩国留学"],
        lookback_hours=48,
        max_items=8,
    )

    assert "2026-08-22 09:00" in prompt
    assert "2026-08-24 09:00" in prompt
    assert "1. AI" in prompt
    assert "2. 韩国留学" in prompt
    assert "最多 8 条" in prompt


def test_parse_result_reads_text_annotations_and_search_sources() -> None:
    text, sources = daily_briefing.parse_responses_api_result(
        {
            "output": [
                {
                    "type": "web_search_call",
                    "action": {
                        "sources": [
                            {"title": "Official B", "url": "https://example.com/b"}
                        ]
                    },
                },
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "一句话判断：有更新。",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "title": "Official A",
                                    "url": "https://example.com/a",
                                },
                                {
                                    "type": "url_citation",
                                    "title": "Duplicate A",
                                    "url": "https://example.com/a/",
                                },
                            ],
                        }
                    ],
                },
            ]
        }
    )

    assert text == "一句话判断：有更新。"
    assert [(source.title, source.url) for source in sources] == [
        ("Official A", "https://example.com/a"),
        ("Official B", "https://example.com/b"),
    ]


def test_split_messages_preserves_all_content() -> None:
    value = "标题\n\n" + "甲" * 160 + "\n\n" + "乙" * 160

    chunks = daily_briefing.split_wechat_messages(value, max_chars=180)

    assert len(chunks) == 2
    assert all(len(chunk) <= 180 for chunk in chunks)
    combined = "\n\n".join(chunk.split("\n", 1)[1] for chunk in chunks)
    assert combined == value


def test_disabled_workflow_skips_without_external_calls() -> None:
    with (
        unittest.mock.patch.object(daily_briefing, "_get_variable", return_value="false"),
        unittest.mock.patch.object(daily_briefing, "generate_briefing") as generate,
        unittest.mock.patch.object(daily_briefing, "send_wechat_text") as send,
    ):
        result = daily_briefing.run_daily_briefing(now=LOCAL_TIME)

    assert result["skipped"] is True
    generate.assert_not_called()
    send.assert_not_called()


def test_workflow_generates_sends_and_persists_sent_state() -> None:
    values = {
        daily_briefing.DAILY_BRIEFING_ENABLED_VAR: "true",
        daily_briefing.DAILY_BRIEFING_OPENAI_API_KEY_VAR: "test-key",
        daily_briefing.DAILY_BRIEFING_OPENAI_API_URL_VAR: "https://api.example.test/responses",
        daily_briefing.DAILY_BRIEFING_MODEL_VAR: "test-model",
        daily_briefing.DAILY_BRIEFING_WECHAT_RECEIVER_VAR: "Tt",
        daily_briefing.DAILY_BRIEFING_LOOKBACK_HOURS_VAR: "48",
        daily_briefing.DAILY_BRIEFING_REQUEST_TIMEOUT_SECONDS_VAR: "30",
        daily_briefing.DAILY_BRIEFING_MAX_ITEMS_VAR: "8",
        daily_briefing.DAILY_BRIEFING_TOPICS_VAR: ["AI"],
        daily_briefing.DAILY_BRIEFING_STATE_VAR: {},
    }
    saved_states: list[dict] = []

    def get_variable(key: str, default=None, deserialize_json: bool = False):
        return values.get(key, default)

    with (
        unittest.mock.patch.object(
            daily_briefing,
            "_get_variable",
            side_effect=get_variable,
        ),
        unittest.mock.patch.object(
            daily_briefing,
            "_set_variable",
            side_effect=lambda _key, value, serialize_json=False: saved_states.append(value),
        ),
        unittest.mock.patch.object(
            daily_briefing,
            "generate_briefing",
            return_value=(
                "一句话判断：有一项重要更新。",
                [daily_briefing.BriefingSource("官方来源", "https://example.com/news")],
            ),
        ) as generate,
        unittest.mock.patch.object(
            daily_briefing,
            "send_wechat_text",
            return_value={"success": True, "sent_count": 1},
        ) as send,
        unittest.mock.patch.object(daily_briefing, "now_local", return_value=LOCAL_TIME),
    ):
        result = daily_briefing.run_daily_briefing(now=LOCAL_TIME)

    assert result["success"] is True
    generate.assert_called_once()
    receiver, messages = send.call_args.args
    assert receiver == "Tt"
    assert "个人每日简报｜2026-08-24" in messages[0]
    assert "https://example.com/news" in messages[0]
    assert saved_states[0]["status"] == "generated"
    assert saved_states[-1]["status"] == "sent"
    assert saved_states[-1]["sent_date"] == "2026-08-24"


def test_same_day_sent_state_is_idempotent() -> None:
    values = {
        daily_briefing.DAILY_BRIEFING_ENABLED_VAR: "true",
        daily_briefing.DAILY_BRIEFING_STATE_VAR: {"sent_date": "2026-08-24"},
    }

    with (
        unittest.mock.patch.object(
            daily_briefing,
            "_get_variable",
            side_effect=lambda key, default=None, deserialize_json=False: values.get(key, default),
        ),
        unittest.mock.patch.object(daily_briefing, "generate_briefing") as generate,
        unittest.mock.patch.object(daily_briefing, "send_wechat_text") as send,
    ):
        result = daily_briefing.run_daily_briefing(now=LOCAL_TIME)

    assert result["reason"] == "already_sent"
    generate.assert_not_called()
    send.assert_not_called()


def test_same_day_cached_draft_is_reused_without_new_search() -> None:
    values = {
        daily_briefing.DAILY_BRIEFING_ENABLED_VAR: "true",
        daily_briefing.DAILY_BRIEFING_OPENAI_API_KEY_VAR: "test-key",
        daily_briefing.DAILY_BRIEFING_WECHAT_RECEIVER_VAR: "Tt",
        daily_briefing.DAILY_BRIEFING_STATE_VAR: {
            "date": "2026-08-24",
            "status": "delivery_failed",
            "message": "☀️ 个人每日简报｜2026-08-24\n\n缓存正文",
            "sources": [
                {"title": "官方来源", "url": "https://example.com/cached"}
            ],
        },
    }
    saved_states: list[dict] = []

    with (
        unittest.mock.patch.object(
            daily_briefing,
            "_get_variable",
            side_effect=lambda key, default=None, deserialize_json=False: values.get(key, default),
        ),
        unittest.mock.patch.object(
            daily_briefing,
            "_set_variable",
            side_effect=lambda _key, value, serialize_json=False: saved_states.append(value),
        ),
        unittest.mock.patch.object(daily_briefing, "generate_briefing") as generate,
        unittest.mock.patch.object(
            daily_briefing,
            "send_wechat_text",
            return_value={"success": True, "sent_count": 1},
        ) as send,
        unittest.mock.patch.object(daily_briefing, "now_local", return_value=LOCAL_TIME),
    ):
        result = daily_briefing.run_daily_briefing(now=LOCAL_TIME)

    assert result["success"] is True
    assert result["source_count"] == 1
    generate.assert_not_called()
    assert send.call_args.args == ("Tt", ["☀️ 个人每日简报｜2026-08-24\n\n缓存正文"])
    assert saved_states[-1]["status"] == "sent"


def test_delivery_failure_keeps_cached_draft_for_retry() -> None:
    values = {
        daily_briefing.DAILY_BRIEFING_ENABLED_VAR: "true",
        daily_briefing.DAILY_BRIEFING_OPENAI_API_KEY_VAR: "test-key",
        daily_briefing.DAILY_BRIEFING_WECHAT_RECEIVER_VAR: "Tt",
        daily_briefing.DAILY_BRIEFING_STATE_VAR: {},
        daily_briefing.DAILY_BRIEFING_TOPICS_VAR: ["AI"],
    }
    saved_states: list[dict] = []

    with (
        unittest.mock.patch.object(
            daily_briefing,
            "_get_variable",
            side_effect=lambda key, default=None, deserialize_json=False: values.get(key, default),
        ),
        unittest.mock.patch.object(
            daily_briefing,
            "_set_variable",
            side_effect=lambda _key, value, serialize_json=False: saved_states.append(value),
        ),
        unittest.mock.patch.object(
            daily_briefing,
            "generate_briefing",
            return_value=("一句话判断：有更新。", []),
        ),
        unittest.mock.patch.object(
            daily_briefing,
            "send_wechat_text",
            side_effect=RuntimeError("offline"),
        ),
        unittest.mock.patch.object(daily_briefing, "now_local", return_value=LOCAL_TIME),
    ):
        with pytest.raises(RuntimeError, match="offline"):
            daily_briefing.run_daily_briefing(now=LOCAL_TIME)

    assert saved_states[0]["status"] == "generated"
    assert saved_states[-1]["status"] == "delivery_failed"
    assert saved_states[-1]["message"] == saved_states[0]["message"]


def test_generate_briefing_uses_web_search_and_bearer_auth() -> None:
    response = unittest.mock.MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "正文", "annotations": []}],
            }
        ]
    }

    with unittest.mock.patch.object(
        openai_client.requests,
        "post",
        return_value=response,
    ) as post:
        body, sources = daily_briefing.generate_briefing(
            api_key="secret",
            api_url="https://api.example.test/responses",
            model="test-model",
            prompt="prompt",
            timeout_seconds=30,
        )

    assert body == "正文"
    assert sources == []
    request = post.call_args
    assert request.kwargs["headers"]["Authorization"] == "Bearer secret"
    assert request.kwargs["json"]["tools"] == [{"type": "web_search"}]
    assert request.kwargs["json"]["store"] is False
    assert request.kwargs["timeout"] == 30
