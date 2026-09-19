"""被动回复锚失效兜底：msg_id 过期/额度耗尽时丢 id 改发主动消息。

事故背景（2026-09-20）：一轮生成耗时 7.8 分钟，发送时群被动回复窗口（5 分钟）
已过，QQ 返回 40034005「回复消息msg_id已过期」，adapter 拿同一个死 msg_id 重试
3 次、网关再重试 2 次，全部失败，回复被静默丢弃。

覆盖：文本（c2c/group/guild）、键盘（审批/更新提示）、富媒体（不重复上传）。
"""

import pytest

from gateway.platforms.base import SendResult


def anchor_error(module, code=40034005, message="回复消息msg_id已过期"):
    """构造一个 QQ 返回的被动回复锚失效错误。"""
    return module.QQBotAPIError(400, "/v2/groups/G/messages", code, message)


class TestAnchorDeadDetection:
    def test_known_codes_are_anchor_failures(self, adapter_module, adapter_instance):
        for code in (
            304026, 304027, 304103,
            40034005, 40034024, 40034025, 40034026, 40034128,
        ):
            exc = adapter_module.QQBotAPIError(400, "/x", code, "irrelevant")
            assert adapter_instance._is_reply_anchor_dead(exc) is True, code

    def test_message_text_without_code(self, adapter_instance):
        assert adapter_instance._is_reply_anchor_dead(
            RuntimeError("QQ Bot API error [400] /v2/groups/G/messages: 回复消息msg_id已过期")
        )
        assert adapter_instance._is_reply_anchor_dead(RuntimeError("msg_id expired"))

    def test_unrelated_errors_are_not_anchor_failures(
        self, adapter_module, adapter_instance
    ):
        for code in (22006, 40034006, 40034105, 40054007, 40054010, 50055001):
            exc = adapter_module.QQBotAPIError(400, "/x", code, "some other failure")
            assert adapter_instance._is_reply_anchor_dead(exc) is False, code
        assert adapter_instance._is_reply_anchor_dead(
            RuntimeError(
                "QQ Bot API error [400] /v2/groups/G/messages: 主动消息失败, 无权限"
            )
        ) is False


class TestSendChunkFallback:
    """send() → _send_chunk()：文本路径（含分片）。"""

    async def test_c2c_expired_anchor_resends_as_active(
        self, adapter_module, adapter_instance
    ):
        seen = []

        async def fake_send(chat_id, content, reply_to=None, keyboard=None):
            seen.append(reply_to)
            if reply_to is not None:
                raise anchor_error(adapter_module)
            return SendResult(success=True, message_id="m1")

        adapter_instance._send_c2c_text = fake_send
        result = await adapter_instance._send_chunk("USER", "hello", "DEAD_ANCHOR")

        assert result.success is True
        assert seen == ["DEAD_ANCHOR", None]

    async def test_group_expired_anchor_resends_as_active(
        self, adapter_module, adapter_instance
    ):
        seen = []

        async def fake_send(chat_id, content, reply_to=None, keyboard=None):
            seen.append(reply_to)
            if reply_to is not None:
                raise anchor_error(adapter_module)
            return SendResult(success=True, message_id="m1")

        adapter_instance._send_group_text = fake_send
        adapter_instance._chat_type_map = {"GROUP": "group"}
        result = await adapter_instance._send_chunk("GROUP", "hello", "DEAD_ANCHOR")

        assert result.success is True
        assert seen == ["DEAD_ANCHOR", None]

    async def test_guild_expired_anchor_resends_as_active(
        self, adapter_module, adapter_instance
    ):
        seen = []

        async def fake_send(chat_id, content, reply_to=None):
            seen.append(reply_to)
            if reply_to is not None:
                raise anchor_error(adapter_module)
            return SendResult(success=True, message_id="m1")

        adapter_instance._send_guild_text = fake_send
        adapter_instance._chat_type_map = {"CHANNEL": "guild"}
        result = await adapter_instance._send_chunk("CHANNEL", "hello", "DEAD_ANCHOR")

        assert result.success is True
        assert seen == ["DEAD_ANCHOR", None]

    async def test_quota_exhausted_also_drops_the_anchor(
        self, adapter_module, adapter_instance
    ):
        seen = []

        async def fake_send(chat_id, content, reply_to=None, keyboard=None):
            seen.append(reply_to)
            if reply_to is not None:
                raise anchor_error(
                    adapter_module, 40034128, "被动回复时间或次数超限"
                )
            return SendResult(success=True, message_id="m1")

        adapter_instance._send_group_text = fake_send
        adapter_instance._chat_type_map = {"GROUP": "group"}
        result = await adapter_instance._send_chunk("GROUP", "hello", "DEAD_ANCHOR")

        assert result.success is True
        assert seen == ["DEAD_ANCHOR", None]

    async def test_fallback_fires_at_most_once(
        self, adapter_module, adapter_instance, monkeypatch
    ):
        seen = []

        async def fake_send(chat_id, content, reply_to=None, keyboard=None):
            seen.append(reply_to)
            raise anchor_error(adapter_module)

        async def no_sleep(_delay):
            return None

        monkeypatch.setattr(adapter_module.asyncio, "sleep", no_sleep)
        adapter_instance._send_group_text = fake_send
        adapter_instance._chat_type_map = {"GROUP": "group"}
        result = await adapter_instance._send_chunk("GROUP", "hello", "DEAD_ANCHOR")

        assert result.success is False
        assert result.retryable is False
        assert seen[0] == "DEAD_ANCHOR"
        # 兜底只把锚丢一次，之后的重试都是主动消息，且次数有界。
        assert set(seen[1:]) == {None}
        assert len(seen) <= 4

    async def test_non_anchor_failure_keeps_the_anchor(
        self, adapter_module, adapter_instance, monkeypatch
    ):
        seen = []
        delays = []

        async def fake_send(chat_id, content, reply_to=None, keyboard=None):
            seen.append(reply_to)
            raise RuntimeError("QQ Bot API error [500] /x: boom")

        async def fake_sleep(delay):
            delays.append(delay)

        monkeypatch.setattr(adapter_module.asyncio, "sleep", fake_sleep)
        adapter_instance._send_group_text = fake_send
        adapter_instance._chat_type_map = {"GROUP": "group"}
        result = await adapter_instance._send_chunk("GROUP", "hello", "ANCHOR")

        assert result.success is False
        assert seen == ["ANCHOR"] * 3
        assert delays == [1.0, 2.0]

    async def test_permanent_error_does_not_retry(
        self, adapter_module, adapter_instance
    ):
        seen = []

        async def fake_send(chat_id, content, reply_to=None, keyboard=None):
            seen.append(reply_to)
            raise RuntimeError("QQ Bot API error [403] /x: forbidden")

        adapter_instance._send_group_text = fake_send
        adapter_instance._chat_type_map = {"GROUP": "group"}
        result = await adapter_instance._send_chunk("GROUP", "hello", "ANCHOR")

        assert result.success is False
        assert seen == ["ANCHOR"]

    async def test_active_message_sends_never_carry_a_dead_anchor(
        self, adapter_module, adapter_instance
    ):
        """没有锚的消息（主动消息）不走兜底，直接发。"""

        async def fake_send(chat_id, content, reply_to=None, keyboard=None):
            assert reply_to is None
            return SendResult(success=True, message_id="m1")

        adapter_instance._send_group_text = fake_send
        adapter_instance._chat_type_map = {"GROUP": "group"}
        result = await adapter_instance._send_chunk("GROUP", "hello", None)

        assert result.success is True


class TestKeyboardFallback:
    """send_with_keyboard()：审批 / 更新提示（按钮不能丢）。"""

    async def test_keyboard_resends_without_anchor(
        self, adapter_module, adapter_instance
    ):
        seen = []

        async def fake_send(chat_id, content, reply_to=None, keyboard=None):
            seen.append((reply_to, keyboard))
            if reply_to is not None:
                raise anchor_error(adapter_module)
            return SendResult(success=True, message_id="m1")

        adapter_instance._send_group_text = fake_send
        adapter_instance._chat_type_map = {"GROUP": "group"}
        keyboard = object()
        result = await adapter_instance.send_with_keyboard(
            "GROUP", "approve?", keyboard, reply_to="DEAD_ANCHOR"
        )

        assert result.success is True
        assert [anchor for anchor, _ in seen] == ["DEAD_ANCHOR", None]
        assert seen[1][1] is keyboard

    async def test_keyboard_c2c_resends_without_anchor(
        self, adapter_module, adapter_instance
    ):
        seen = []

        async def fake_send(chat_id, content, reply_to=None, keyboard=None):
            seen.append(reply_to)
            if reply_to is not None:
                raise anchor_error(adapter_module)
            return SendResult(success=True, message_id="m1")

        adapter_instance._send_c2c_text = fake_send
        result = await adapter_instance.send_with_keyboard(
            "USER", "approve?", object(), reply_to="DEAD_ANCHOR"
        )

        assert result.success is True
        assert seen == ["DEAD_ANCHOR", None]

    async def test_keyboard_unrelated_error_is_single_attempt(
        self, adapter_module, adapter_instance
    ):
        seen = []

        async def fake_send(chat_id, content, reply_to=None, keyboard=None):
            seen.append(reply_to)
            raise RuntimeError("QQ Bot API error [500] /x: boom")

        adapter_instance._send_group_text = fake_send
        adapter_instance._chat_type_map = {"GROUP": "group"}
        result = await adapter_instance.send_with_keyboard(
            "GROUP", "approve?", object(), reply_to="ANCHOR"
        )

        assert result.success is False
        assert seen == ["ANCHOR"]

    async def test_keyboard_without_anchor_is_unaffected(
        self, adapter_module, adapter_instance
    ):
        async def fake_send(chat_id, content, reply_to=None, keyboard=None):
            assert reply_to is None
            return SendResult(success=True, message_id="m1")

        adapter_instance._send_c2c_text = fake_send
        result = await adapter_instance.send_with_keyboard("USER", "approve?", object())

        assert result.success is True


class TestMediaFallback:
    """_send_media()：图片 / 语音 / 视频 / 文件。"""

    async def test_media_resends_without_anchor_and_without_reupload(
        self, adapter_module, adapter_instance
    ):
        posts = []
        uploads = []

        async def fake_upload(target_type, target_id, file_type, **kwargs):
            uploads.append(target_id)
            return {"file_info": "FILE_INFO"}

        async def fake_api(method, path, body=None, timeout=None):
            posts.append(dict(body))
            if body.get("msg_id"):
                raise anchor_error(adapter_module)
            return {"id": "sent-1"}

        adapter_instance._upload_media = fake_upload
        adapter_instance._api_request = fake_api
        adapter_instance._chat_type_map = {"GROUP": "group"}
        result = await adapter_instance._send_media(
            "GROUP", "https://example.com/a.png",
            adapter_module.MEDIA_TYPE_IMAGE, "image", "caption", "DEAD_ANCHOR",
        )

        assert result.success is True
        assert result.message_id == "sent-1"
        # 只上传一次；第二次发送复用 file_info。
        assert uploads == ["GROUP"]
        assert posts[0]["msg_id"] == "DEAD_ANCHOR"
        assert "msg_id" not in posts[1]
        assert posts[1]["media"] == {"file_info": "FILE_INFO"}

    async def test_media_unrelated_error_is_not_retried(
        self, adapter_module, adapter_instance
    ):
        posts = []

        async def fake_upload(target_type, target_id, file_type, **kwargs):
            return {"file_info": "FILE_INFO"}

        async def fake_api(method, path, body=None, timeout=None):
            posts.append(dict(body))
            raise adapter_module.QQBotAPIError(
                400, "/x", 40054007, "消息长度超限"
            )

        adapter_instance._upload_media = fake_upload
        adapter_instance._api_request = fake_api
        adapter_instance._chat_type_map = {"GROUP": "group"}
        result = await adapter_instance._send_media(
            "GROUP", "https://example.com/a.png",
            adapter_module.MEDIA_TYPE_IMAGE, "image", None, "ANCHOR",
        )

        assert result.success is False
        assert len(posts) == 1


class TestApiRequestErrCode:
    """_api_request() 必须把 err_code 暴露出来，兜底才能按错误码判断。"""

    async def test_err_code_and_message_are_carried(self, adapter_module, adapter_instance):
        class _Response:
            status_code = 400
            text = ""

            @staticmethod
            def json():
                return {"err_code": 40034005, "message": "回复消息msg_id已过期"}

        class _Client:
            async def request(self, *args, **kwargs):
                return _Response()

        async def _token():
            return "token"

        adapter_instance._http_client = _Client()
        adapter_instance._ensure_token = _token

        with pytest.raises(adapter_module.QQBotAPIError) as excinfo:
            await adapter_instance._api_request("POST", "/v2/groups/G/messages", {})

        exc = excinfo.value
        assert isinstance(exc, RuntimeError)  # 现有 except RuntimeError 仍能接住
        assert exc.err_code == 40034005
        assert exc.status == 400
        assert exc.api_message == "回复消息msg_id已过期"
        assert str(exc).startswith("QQ Bot API error [400] /v2/groups/G/messages:")
        assert "err_code=40034005" in str(exc)

    async def test_missing_err_code_is_tolerated(self, adapter_module, adapter_instance):
        class _Response:
            status_code = 500
            text = ""

            @staticmethod
            def json():
                return {"message": "消息发送异常，请稍后重试"}

        class _Client:
            async def request(self, *args, **kwargs):
                return _Response()

        async def _token():
            return "token"

        adapter_instance._http_client = _Client()
        adapter_instance._ensure_token = _token

        with pytest.raises(adapter_module.QQBotAPIError) as excinfo:
            await adapter_instance._api_request("POST", "/v2/users/U/messages", {})

        assert excinfo.value.err_code is None
        assert adapter_instance._is_reply_anchor_dead(excinfo.value) is False
