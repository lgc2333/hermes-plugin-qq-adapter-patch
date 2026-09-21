"""聊天类型路由：重启后不再把群 openid 发到单聊端点。

事故（2026-09-20）：网关重启后 `_chat_type_map` 为空，`_guess_chat_type` 默认回
`c2c`，于是 delivery ledger 补投的那条群消息打到 `/v2/users/<群openid>/messages`，
QQ 回 `40011028 请求的资源不存在(用户/群已注销)`，消息永远送不到。

两层修法——① `connect()` 时从 `gateway_routing` 回填 chat_type（不再猜错）；
② 真猜错时按错误码 `40011028` 翻转端点重发一次（文本/键盘/媒体三处）。
非网络类错误最终返回 `retryable=False`，交给上层丢弃而不是反复重放。
"""

import sqlite3

import hermes_constants
import pytest

from gateway.platforms.base import SendResult


def wrong_endpoint_error(module, chat_id="GROUP"):
    return module.QQBotAPIError(
        400,
        f"/v2/users/{chat_id}/messages",
        40011028,
        "请求的资源不存在(用户/群已注销)",
    )


class TestChatTypeHelpers:
    def test_wrong_endpoint_detected_by_code_and_text(
        self, adapter_module, adapter_instance
    ):
        assert adapter_instance._is_wrong_endpoint(wrong_endpoint_error(adapter_module))
        assert adapter_instance._is_wrong_endpoint(
            RuntimeError("QQ Bot API error [400] /x: 请求的资源不存在(用户/群已注销)")
        )
        assert not adapter_instance._is_wrong_endpoint(
            adapter_module.QQBotAPIError(400, "/x", 40034005, "回复消息msg_id已过期")
        )
        assert not adapter_instance._is_wrong_endpoint(
            RuntimeError("QQ Bot API error [500] /x: boom")
        )

    def test_flip_is_symmetric_and_skips_guild(self, adapter_instance):
        assert adapter_instance._flip_chat_type("c2c") == "group"
        assert adapter_instance._flip_chat_type("group") == "c2c"
        assert adapter_instance._flip_chat_type("guild") is None
        assert adapter_instance._flip_chat_type("") is None

    def test_session_key_kinds_normalize(self, adapter_instance):
        assert adapter_instance._normalize_chat_type("dm") == "c2c"
        assert adapter_instance._normalize_chat_type("c2c") == "c2c"
        assert adapter_instance._normalize_chat_type("GROUP") == "group"
        assert adapter_instance._normalize_chat_type("guild") == "guild"
        assert adapter_instance._normalize_chat_type("nonsense") is None


class TestEndpointFlip:
    async def test_text_chunk_flips_to_the_group_endpoint(
        self, adapter_module, adapter_instance
    ):
        calls = []

        async def fake_c2c(chat_id, content, reply_to=None, keyboard=None):
            calls.append("c2c")
            raise wrong_endpoint_error(adapter_module)

        async def fake_group(chat_id, content, reply_to=None, keyboard=None):
            calls.append("group")
            return SendResult(success=True, message_id="m1")

        adapter_instance._send_c2c_text = fake_c2c
        adapter_instance._send_group_text = fake_group

        result = await adapter_instance._send_chunk("GROUP", "hello")

        assert result.success is True
        assert calls == ["c2c", "group"]

    async def test_flip_runs_at_most_once_and_fails_closed(
        self, adapter_module, adapter_instance
    ):
        calls = []

        async def fake_c2c(chat_id, content, reply_to=None, keyboard=None):
            calls.append("c2c")
            raise wrong_endpoint_error(adapter_module)

        async def fake_group(chat_id, content, reply_to=None, keyboard=None):
            calls.append("group")
            raise wrong_endpoint_error(adapter_module)

        adapter_instance._send_c2c_text = fake_c2c
        adapter_instance._send_group_text = fake_group

        result = await adapter_instance._send_chunk("GROUP", "hello")

        assert result.success is False
        assert result.retryable is False
        assert calls == ["c2c", "group"]

    async def test_unknown_chat_id_still_fails_closed_without_flip_target(
        self, adapter_module, adapter_instance
    ):
        calls = []

        async def fake_guild(chat_id, content, reply_to=None, keyboard=None):
            calls.append("guild")
            raise wrong_endpoint_error(adapter_module)

        adapter_instance._send_guild_text = fake_guild
        adapter_instance._chat_type_map = {"CHANNEL": "guild"}

        result = await adapter_instance._send_chunk("CHANNEL", "hello")

        assert result.success is False
        assert calls == ["guild"]

    async def test_keyboard_flips_and_keeps_the_button_payload(
        self, adapter_module, adapter_instance
    ):
        seen = []

        async def fake_send(chat_id, content, reply_to=None, keyboard=None):
            seen.append(keyboard)
            if len(seen) == 1:
                raise wrong_endpoint_error(adapter_module)
            return SendResult(success=True, message_id="m1")

        adapter_instance._send_c2c_text = fake_send
        adapter_instance._send_group_text = fake_send
        keyboard = object()

        result = await adapter_instance.send_with_keyboard("GROUP", "approve?", keyboard)

        assert result.success is True
        assert seen == [keyboard, keyboard]

    async def test_media_retries_upload_on_the_other_endpoint(
        self, adapter_module, adapter_instance
    ):
        uploads, posts = [], []

        async def fake_upload(target_type, target_id, file_type, **kwargs):
            uploads.append(target_type)
            return {"file_info": "FILE_INFO"}

        async def fake_api(method, path, body=None, timeout=None):
            posts.append(path)
            if "/v2/users/" in path:
                raise wrong_endpoint_error(adapter_module)
            return {"id": "sent-1"}

        adapter_instance._upload_media = fake_upload
        adapter_instance._api_request = fake_api

        result = await adapter_instance._send_media(
            "GROUP", "https://example.com/a.png",
            adapter_module.MEDIA_TYPE_IMAGE, "image", None, None,
        )

        assert result.success is True
        assert uploads == ["c2c", "group"]
        assert posts == ["/v2/users/GROUP/messages", "/v2/groups/GROUP/messages"]


class TestChatTypeSeed:
    def _make_db(self, tmp_path, keys):
        db = tmp_path / "state.db"
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE gateway_routing (scope TEXT, session_key TEXT, entry_json TEXT)")
        for key in keys:
            con.execute("INSERT INTO gateway_routing VALUES ('/s', ?, '{}')", (key,))
        con.commit()
        con.close()
        return db

    def test_seeds_qqbot_chats_and_normalizes_dm(
        self, adapter_module, adapter_instance, tmp_path, monkeypatch
    ):
        self._make_db(tmp_path, [
            "agent:main:qqbot:group:G1:U1",
            "agent:main:qqbot:dm:U2",
            "agent:coder:qqbot:group:G3:U1",
            "agent:main:telegram:dm:T1",
            "agent:main:qqbot:guild:CH1",
        ])
        monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: tmp_path)

        seeded = adapter_instance._seed_chat_types_from_routing()

        assert seeded == 4
        assert adapter_instance._chat_type_map == {
            "G1": "group",
            "U2": "c2c",
            "G3": "group",
            "CH1": "guild",
        }

    def test_existing_kinds_are_not_overwritten(
        self, adapter_module, adapter_instance, tmp_path, monkeypatch
    ):
        self._make_db(tmp_path, ["agent:main:qqbot:group:G1:U1"])
        monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: tmp_path)
        adapter_instance._chat_type_map = {"G1": "guild"}

        adapter_instance._seed_chat_types_from_routing()

        assert adapter_instance._chat_type_map["G1"] == "guild"

    def test_missing_database_is_not_an_error(
        self, adapter_module, adapter_instance, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: tmp_path)

        assert adapter_instance._seed_chat_types_from_routing() == 0
