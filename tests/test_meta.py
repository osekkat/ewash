import pytest

from app import meta


@pytest.mark.asyncio
async def test_post_4xx_raises_meta_send_error_with_body(monkeypatch):
    body = '{"error":{"message":"Template not approved","code":132001}}'
    captured = {}

    class FakeResponse:
        status_code = 400
        text = body

        def json(self):
            raise AssertionError("4xx responses should not be decoded as success JSON")

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb

        async def post(self, url, *, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(meta.httpx, "AsyncClient", FakeAsyncClient)

    with pytest.raises(meta.MetaSendError) as exc_info:
        await meta._post({"type": "template"})

    exc = exc_info.value
    assert exc.status_code == 400
    assert exc.body == body
    assert exc.request_path == meta.GRAPH_API_PATH
    assert body in str(exc)
    assert captured["url"] == meta.GRAPH_API_URL
