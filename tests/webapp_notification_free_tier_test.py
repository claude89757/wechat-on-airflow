"""Host observations must stay fresh; the removed D1 throttle is not a fallback."""

from unittest.mock import Mock, patch

import requests

from wechat_airflow.notifications import webapp


def response():
    value = Mock()
    value.json.return_value = {
        "success": True,
        "wechatGate": {
            "allowed": True,
            "evaluatedAt": "2026-09-05T00:00:00Z",
            "validUntil": "2026-09-05T00:01:00Z",
        },
    }
    return value


def test_unchanged_polls_still_refresh_local_postgresql():
    with (
        patch.object(webapp, "_host_token", return_value="token"),
        patch.object(webapp, "_get_variable", return_value=5),
        patch.object(webapp, "_cache_gate"),
        patch.object(webapp.requests, "post", return_value=response()) as post,
    ):
        for _ in range(2):
            assert webapp.publish_venue_observation("tops", "TOPS", [], healthy=True)["success"]
    assert post.call_count == 2
    assert all(call.args[0].startswith(webapp.LOCAL_API) for call in post.call_args_list)


def test_failed_poll_retries_on_next_natural_poll_without_cloudflare():
    with (
        patch.object(webapp, "_host_token", return_value="token"),
        patch.object(webapp, "_get_variable", return_value=5),
        patch.object(webapp, "_cache_gate"),
        patch.object(
            webapp.requests, "post", side_effect=[requests.ConnectTimeout(), response()]
        ) as post,
    ):
        assert not webapp.publish_venue_observation("tops", "TOPS", [], healthy=True)["success"]
        assert webapp.publish_venue_observation("tops", "TOPS", [], healthy=True)["success"]
    assert post.call_count == 2
    assert all(call.args[0].startswith(webapp.LOCAL_API) for call in post.call_args_list)
