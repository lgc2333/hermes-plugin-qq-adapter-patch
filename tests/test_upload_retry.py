"""上传重试分类：网络/服务端瞬时错误才重试，业务拒绝立刻失败。

背景：`_upload_media` 原先按子串 `"400"` 判永久错误，而错误串里本来就带
`[400]`，于是任何 4xx 业务错误——包括 QQ 在 400 响应里返回的
`50055001 消息发送异常，请稍后重试`——都被直接放弃，3 次重试形同虚设；
与此同时真正的网络错误因为根本没被 except 捕获，也从不重试。
"""

import httpx
import pytest


def api_error(module, code, message="whatever"):
    return module.QQBotAPIError(400, "/v2/users/U/files", code, message)


class TestUploadRetryClassification:
    def test_business_rejections_fail_fast(self, adapter_module, adapter_instance):
        for code in (40011028, 40034005, 40034105, 40054007, 40054010, 304103):
            assert adapter_instance._is_upload_retryable(api_error(adapter_module, code)) is False, code

    def test_transient_qq_codes_retry(self, adapter_module, adapter_instance):
        for code in (40034004, 50055001, 50055006, 50055099):
            assert adapter_instance._is_upload_retryable(api_error(adapter_module, code)) is True, code

    def test_transport_and_timeout_retry(self, adapter_instance):
        assert adapter_instance._is_upload_retryable(
            httpx.ConnectError("connection reset")
        ) is True
        assert adapter_instance._is_upload_retryable(
            httpx.ReadTimeout("read timed out")
        ) is True
        assert adapter_instance._is_upload_retryable(
            RuntimeError("QQ Bot API timeout [/v2/users/U/files]: timed out")
        ) is True

    def test_plain_business_errors_fail_fast(self, adapter_instance):
        assert adapter_instance._is_upload_retryable(
            RuntimeError("QQ Bot API error [400] /x: 消息长度超限")
        ) is False
        assert adapter_instance._is_upload_retryable(
            RuntimeError("HTTP client not initialized — not connected?")
        ) is False


class TestUploadMediaRetryLoop:
    async def test_business_error_is_raised_without_retry(
        self, adapter_module, adapter_instance, monkeypatch
    ):
        calls = []

        async def fake_api(method, path, body=None, timeout=None):
            calls.append(path)
            raise adapter_module.QQBotAPIError(
                400, path, 40011028, "请求的资源不存在(用户/群已注销)"
            )

        async def no_sleep(_delay):
            return None

        monkeypatch.setattr(adapter_module.asyncio, "sleep", no_sleep)
        adapter_instance._api_request = fake_api

        with pytest.raises(adapter_module.QQBotAPIError):
            await adapter_instance._upload_media(
                "c2c", "U", adapter_module.MEDIA_TYPE_IMAGE, url="https://example.com/a.png"
            )

        assert len(calls) == 1

    async def test_transient_error_is_retried_three_times(
        self, adapter_module, adapter_instance, monkeypatch
    ):
        calls = []

        async def fake_api(method, path, body=None, timeout=None):
            calls.append(path)
            raise adapter_module.QQBotAPIError(400, path, 50055001, "消息发送异常，请稍后重试")

        async def no_sleep(_delay):
            return None

        monkeypatch.setattr(adapter_module.asyncio, "sleep", no_sleep)
        adapter_instance._api_request = fake_api

        with pytest.raises(adapter_module.QQBotAPIError):
            await adapter_instance._upload_media(
                "c2c", "U", adapter_module.MEDIA_TYPE_IMAGE, url="https://example.com/a.png"
            )

        assert len(calls) == 3

    async def test_transport_error_is_retried(
        self, adapter_module, adapter_instance, monkeypatch
    ):
        calls = []

        async def fake_api(method, path, body=None, timeout=None):
            calls.append(path)
            raise httpx.ConnectError("connection reset by peer")

        async def no_sleep(_delay):
            return None

        monkeypatch.setattr(adapter_module.asyncio, "sleep", no_sleep)
        adapter_instance._api_request = fake_api

        with pytest.raises(httpx.ConnectError):
            await adapter_instance._upload_media(
                "c2c", "U", adapter_module.MEDIA_TYPE_IMAGE, url="https://example.com/a.png"
            )

        assert len(calls) == 3

    async def test_success_on_first_attempt_does_not_retry(
        self, adapter_module, adapter_instance
    ):
        calls = []

        async def fake_api(method, path, body=None, timeout=None):
            calls.append(path)
            return {"file_info": "FILE_INFO"}

        adapter_instance._api_request = fake_api

        result = await adapter_instance._upload_media(
            "c2c", "U", adapter_module.MEDIA_TYPE_IMAGE, url="https://example.com/a.png"
        )

        assert result == {"file_info": "FILE_INFO"}
        assert len(calls) == 1
