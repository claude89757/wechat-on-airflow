from __future__ import annotations

from typing import cast

import requests

from wechat_airflow.briefings.models import (
    BriefingSource,
    DailyBriefingApiError,
    JsonDict,
)


def _response_payload(*, model: str, prompt: str) -> JsonDict:
    return {
        "model": model,
        "input": prompt,
        "tools": [{"type": "web_search"}],
        "include": ["web_search_call.action.sources"],
        "reasoning": {"effort": "low"},
        "max_output_tokens": 2400,
        "store": False,
    }


def source_from_mapping(value: object) -> BriefingSource | None:
    if not isinstance(value, dict):
        return None
    source = cast(JsonDict, value)
    nested = source.get("url_citation")
    if isinstance(nested, dict):
        source = cast(JsonDict, nested)
    url = str(source.get("url") or "").strip()
    if not url.startswith(("https://", "http://")):
        return None
    title = str(source.get("title") or source.get("name") or url).strip()
    return BriefingSource(title=title or url, url=url)


def parse_responses_api_result(payload: object) -> tuple[str, list[BriefingSource]]:
    if not isinstance(payload, dict):
        raise DailyBriefingApiError("Responses API returned an invalid JSON object")
    data = cast(JsonDict, payload)
    text_parts: list[str] = []
    cited_sources: list[BriefingSource] = []
    searched_sources: list[BriefingSource] = []

    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        text_parts.append(output_text.strip())

    output = data.get("output")
    if isinstance(output, list):
        for raw_item in output:
            if not isinstance(raw_item, dict):
                continue
            item = cast(JsonDict, raw_item)
            content = item.get("content")
            if isinstance(content, list):
                for raw_part in content:
                    if not isinstance(raw_part, dict):
                        continue
                    part = cast(JsonDict, raw_part)
                    part_text = part.get("text")
                    if isinstance(part_text, str) and part_text.strip():
                        text_parts.append(part_text.strip())
                    annotations = part.get("annotations")
                    if isinstance(annotations, list):
                        for annotation in annotations:
                            source = source_from_mapping(annotation)
                            if source is not None:
                                cited_sources.append(source)

            action = item.get("action")
            if isinstance(action, dict):
                action_sources = action.get("sources")
                if isinstance(action_sources, list):
                    for raw_source in action_sources:
                        source = source_from_mapping(raw_source)
                        if source is not None:
                            searched_sources.append(source)

    deduplicated_text: list[str] = []
    seen_text: set[str] = set()
    for part in text_parts:
        if part not in seen_text:
            deduplicated_text.append(part)
            seen_text.add(part)
    text = "\n\n".join(deduplicated_text).strip()
    if not text:
        error = data.get("error")
        detail = str(error)[:500] if error else "no output text"
        raise DailyBriefingApiError(f"Responses API produced no briefing text: {detail}")

    deduplicated_sources: list[BriefingSource] = []
    seen_urls: set[str] = set()
    for source in [*cited_sources, *searched_sources]:
        normalized_url = source.url.rstrip("/")
        if normalized_url in seen_urls:
            continue
        seen_urls.add(normalized_url)
        deduplicated_sources.append(source)
    return text, deduplicated_sources


def generate_briefing(
    *,
    api_key: str,
    api_url: str,
    model: str,
    prompt: str,
    timeout_seconds: int,
) -> tuple[str, list[BriefingSource]]:
    try:
        response = requests.post(
            api_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=_response_payload(model=model, prompt=prompt),
            timeout=timeout_seconds,
        )
    except requests.RequestException as exc:
        raise DailyBriefingApiError(f"Responses API request failed: {exc}") from exc

    if response.status_code >= 400:
        body = response.text[:1000]
        raise DailyBriefingApiError(
            f"Responses API returned HTTP {response.status_code}: {body}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise DailyBriefingApiError("Responses API returned non-JSON content") from exc
    return parse_responses_api_result(payload)
