from unittest.mock import Mock, patch

import pytest
import requests

from wechat_airflow.notifications import webapp


@pytest.mark.parametrize("allowed", [True, False])
def test_gate_always_reads_local_authority_not_stale_web_cache(allowed):
    response = Mock()
    response.json.return_value = {"allowed": allowed}
    with (
        patch.object(webapp, "_host_token", return_value="token"),
        patch.object(webapp.requests, "get", return_value=response) as get,
    ):
        assert (
            webapp.wechat_delivery_allowed("tops", {"wechatGate": {"allowed": not allowed}})
            is allowed
        )
    assert get.call_args.args[0].startswith(webapp.LOCAL_API)
    assert get.call_args.kwargs["timeout"] == 5


def test_gate_unavailable_is_unknown_not_false_no_subscription():
    with (
        patch.object(webapp, "_host_token", return_value="token"),
        patch.object(webapp.requests, "get", side_effect=requests.ConnectionError),
    ):
        with pytest.raises(requests.ConnectionError):
            webapp.wechat_delivery_allowed("tops")
