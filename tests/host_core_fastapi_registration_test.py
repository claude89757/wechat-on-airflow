from fastapi.routing import APIRoute

from wechat_airflow.host_core.api import API_PREFIX, app


def test_admin_invites_route_disables_inferred_response_model() -> None:
    route = next(
        candidate
        for candidate in app.routes
        if isinstance(candidate, APIRoute)
        and candidate.path == f"{API_PREFIX}/admin/invites"
    )

    assert route.response_model is None
    assert route.methods == {"GET", "POST"}
