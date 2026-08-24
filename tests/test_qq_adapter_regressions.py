import time
from unittest.mock import AsyncMock

import pytest
from gateway.config import PlatformConfig
from gateway.platforms.base import SendResult

from conftest import add_obligation


PASSIVE_QUOTA_ERROR = "被动回复时间或者次数超过限制"


async def test_dm_ledger_does_not_pollute_chat_type_or_route_to_group(
    adapter_instance, temp_hermes_home
):
    add_obligation(
        temp_hermes_home,
        chat_id="USER_DM",
        content="hello",
        session_key="agent:main:qqbot:dm:USER_DM",
    )
    sent = []

    async def send_c2c(openid, content, reply_to=None, keyboard=None):
        sent.append(("c2c", openid, reply_to, content))
        return SendResult(success=True, message_id="ok-c2c")

    async def send_group(group_openid, content, reply_to=None, keyboard=None):
        sent.append(("group", group_openid, reply_to, content))
        return SendResult(success=True, message_id="wrong-group")

    adapter_instance._send_c2c_text = send_c2c
    adapter_instance._send_group_text = send_group

    result = await adapter_instance.send("USER_DM", "hello")

    assert result.success
    assert sent == [("c2c", "USER_DM", None, "hello")]
    assert adapter_instance._chat_type_map["USER_DM"] == "c2c"


async def test_known_c2c_skips_group_fallback_resolution(adapter_instance, temp_hermes_home):
    add_obligation(
        temp_hermes_home,
        chat_id="USER_DM",
        content="hello",
        session_key="agent:main:qqbot:group:USER_DM:WRONG_MEMBER",
    )
    adapter_instance._chat_type_map["USER_DM"] = "c2c"
    sent = []

    async def send_c2c(openid, content, reply_to=None, keyboard=None):
        sent.append(("c2c", openid))
        return SendResult(success=True, message_id="ok-c2c")

    async def send_group(group_openid, content, reply_to=None, keyboard=None):
        sent.append(("group", group_openid))
        return SendResult(success=True, message_id="wrong-group")

    adapter_instance._send_c2c_text = send_c2c
    adapter_instance._send_group_text = send_group

    await adapter_instance.send("USER_DM", "hello")

    assert sent == [("c2c", "USER_DM")]
    assert adapter_instance._chat_type_map["USER_DM"] == "c2c"


def test_group_member_allowlist_accepts_listed_member(adapter_module):
    adapter = adapter_module.QQAdapterPatchAdapter(
        PlatformConfig(
            enabled=True,
            extra={
                "app_id": "a",
                "client_secret": "b",
                "group_policy": "allowlist",
                "group_allow_from": [" GROUP "],
                "group_member_allow_from": [" MEMBER1 "],
            },
        )
    )

    assert adapter._is_group_allowed("group", "member1") is True


def test_group_member_allowlist_rejects_unlisted_member(adapter_module):
    adapter = adapter_module.QQAdapterPatchAdapter(
        PlatformConfig(
            enabled=True,
            extra={
                "app_id": "a",
                "client_secret": "b",
                "group_policy": "allowlist",
                "group_allow_from": ["GROUP"],
                "group_member_allow_from": ["MEMBER1"],
            },
        )
    )

    assert adapter._is_group_allowed("GROUP", "MEMBER2") is False


def test_group_member_allowlist_reads_env_fallback(adapter_module, monkeypatch):
    monkeypatch.setenv("QQ_GROUP_ALLOWED_MEMBERS", "MEMBER1, MEMBER2")
    adapter = adapter_module.QQAdapterPatchAdapter(
        PlatformConfig(
            enabled=True,
            extra={
                "app_id": "a",
                "client_secret": "b",
                "group_policy": "allowlist",
                "group_allow_from": ["GROUP"],
            },
        )
    )

    assert adapter._group_member_allow_from == ["MEMBER1", "MEMBER2"]
    assert adapter._is_group_allowed("GROUP", "MEMBER2") is True
    assert adapter._is_group_allowed("GROUP", "MEMBER3") is False


def test_group_member_allowlist_empty_list_allows_any_member(adapter_module):
    adapter = adapter_module.QQAdapterPatchAdapter(
        PlatformConfig(
            enabled=True,
            extra={
                "app_id": "a",
                "client_secret": "b",
                "group_policy": "allowlist",
                "group_allow_from": ["GROUP"],
                "group_member_allow_from": [],
            },
        )
    )

    assert adapter._is_group_allowed("GROUP", "ANY_MEMBER") is True


async def test_send_chunk_drops_reply_to_after_passive_quota_error(adapter_instance):
    adapter_instance._chat_type_map["USER"] = "c2c"
    calls = []

    async def send_c2c(openid, content, reply_to=None, keyboard=None):
        calls.append(reply_to)
        if len(calls) == 1:
            raise RuntimeError(PASSIVE_QUOTA_ERROR)
        raise RuntimeError("active send still failed")

    adapter_instance._send_c2c_text = send_c2c

    result = await adapter_instance._send_chunk("USER", "hello", reply_to="MSG1")

    assert calls == ["MSG1", None]
    assert not result.success
    assert result.retryable is False
    assert result.error == "active send still failed"


async def test_send_chunk_quota_error_without_reply_to_does_not_retry_without_msg_id(
    adapter_instance,
):
    adapter_instance._chat_type_map["USER"] = "c2c"
    calls = []

    async def send_c2c(openid, content, reply_to=None, keyboard=None):
        calls.append(reply_to)
        raise RuntimeError(PASSIVE_QUOTA_ERROR)

    adapter_instance._send_c2c_text = send_c2c

    result = await adapter_instance._send_chunk("USER", "hello", reply_to=None)

    assert calls == [None]
    assert not result.success
    assert result.retryable is False


async def test_send_uses_recent_last_msg_id_as_passive_reply(adapter_instance):
    adapter_instance._chat_type_map["USER"] = "c2c"
    adapter_instance._last_msg_id["USER"] = "RECENT"
    adapter_instance._last_msg_id_ts["USER"] = time.time()
    calls = []

    async def send_c2c(openid, content, reply_to=None, keyboard=None):
        calls.append(reply_to)
        return SendResult(success=True)

    adapter_instance._send_c2c_text = send_c2c

    await adapter_instance.send("USER", "hello")

    assert calls == ["RECENT"]


async def test_send_does_not_use_expired_last_msg_id(adapter_instance):
    adapter_instance._chat_type_map["USER"] = "c2c"
    adapter_instance._last_msg_id["USER"] = "OLD"
    adapter_instance._last_msg_id_ts["USER"] = time.time() - 301
    calls = []

    async def send_c2c(openid, content, reply_to=None, keyboard=None):
        calls.append(reply_to)
        return SendResult(success=True)

    adapter_instance._send_c2c_text = send_c2c

    await adapter_instance.send("USER", "hello")

    assert calls == [None]


def test_group_ledger_still_resolves_member(adapter_instance, temp_hermes_home):
    add_obligation(
        temp_hermes_home,
        chat_id="GROUP",
        content="group hello",
        session_key="agent:main:qqbot:group:GROUP:MEMBER1",
    )

    member, authoritative = adapter_instance._member_from_delivery_ledger(
        "GROUP", "group hello"
    )

    assert (member, authoritative) == ("MEMBER1", True)


def test_ledger_ambiguous_group_members_is_non_authoritative(
    adapter_instance, temp_hermes_home
):
    add_obligation(
        temp_hermes_home,
        chat_id="GROUP",
        content="same",
        session_key="agent:main:qqbot:group:GROUP:MEMBER1",
    )
    add_obligation(
        temp_hermes_home,
        chat_id="GROUP",
        content="same",
        session_key="agent:main:qqbot:group:GROUP:MEMBER2",
    )

    member, authoritative = adapter_instance._member_from_delivery_ledger("GROUP", "same")

    assert member is None
    assert authoritative is False
    assert adapter_instance._chat_type_map["GROUP"] == "group"


def test_ledger_recovered_reply_matches_original_content(adapter_instance, temp_hermes_home):
    add_obligation(
        temp_hermes_home,
        chat_id="GROUP",
        content="original body",
        session_key="agent:main:qqbot:group:GROUP:MEMBER1",
    )

    member, authoritative = adapter_instance._member_from_delivery_ledger(
        "GROUP", "♻️ Recovered reply\n\noriginal body"
    )

    assert (member, authoritative) == ("MEMBER1", True)


def test_ledger_mixed_dm_and_group_rows_prefers_unique_group_member(
    adapter_instance, temp_hermes_home
):
    add_obligation(
        temp_hermes_home,
        chat_id="GROUP",
        content="same",
        session_key="agent:main:qqbot:dm:GROUP",
    )
    add_obligation(
        temp_hermes_home,
        chat_id="GROUP",
        content="same",
        session_key="agent:main:qqbot:group:GROUP:MEMBER1",
    )

    member, authoritative = adapter_instance._member_from_delivery_ledger("GROUP", "same")

    assert (member, authoritative) == ("MEMBER1", True)


def test_session_member_from_key_rejects_non_matching_sessions(adapter_instance):
    fn = adapter_instance._session_member_from_key

    assert fn("agent:main:qqbot:group:GROUP:MEMBER1", "GROUP") == "MEMBER1"
    assert fn("agent:main:qqbot:dm:MEMBER1", "GROUP") is None
    assert fn("agent:main:telegram:group:GROUP:MEMBER1", "GROUP") is None
    assert fn("agent:main:qqbot:group:OTHER:MEMBER1", "GROUP") is None


def test_reply_anchor_resolves_exact_member_and_group(adapter_instance):
    adapter_instance._remember_group_msg_sender("MSG1", "GROUP", "MEMBER1")
    adapter_instance._remember_group_msg_sender("MSG2", "GROUP", "MEMBER2")

    assert adapter_instance._member_for_reply_anchor("GROUP", "MSG1") == "MEMBER1"
    assert adapter_instance._member_for_reply_anchor("OTHER", "MSG1") is None


def test_reply_anchor_expires_and_is_pruned(adapter_instance):
    adapter_instance._group_msg_sender_ttl = 1
    adapter_instance._group_msg_sender["OLD"] = ("GROUP", "MEMBER1", time.time() - 5)

    assert adapter_instance._member_for_reply_anchor("GROUP", "OLD") is None
    assert "OLD" not in adapter_instance._group_msg_sender


def test_metadata_group_member_requires_matching_chat_id(adapter_instance):
    wrong = adapter_instance._metadata_group_member(
        "GROUP_A",
        {
            "source_chat_type": "group",
            "source_chat_id": "GROUP_B",
            "source_user_id": "MEMBER_B",
        },
    )
    assert wrong is None
    assert "GROUP_A" not in adapter_instance._chat_type_map

    ok = adapter_instance._metadata_group_member(
        "GROUP_A",
        {
            "source_chat_type": "group",
            "source_chat_id": "GROUP_A",
            "source_user_id": "MEMBER_A",
        },
    )
    assert ok == "MEMBER_A"
    assert adapter_instance._chat_type_map["GROUP_A"] == "group"


async def test_group_send_failure_falls_back_to_metadata_member_not_last_sender(
    adapter_instance,
):
    adapter_instance._chat_type_map["GROUP"] = "group"
    adapter_instance._group_last_sender["GROUP"] = "MEMBER_WRONG"
    adapter_instance._last_msg_id["MEMBER_OK"] = "C2C_MSG"
    adapter_instance._last_msg_id_ts["MEMBER_OK"] = time.time()
    calls = []

    async def send_group(group_openid, content, reply_to=None, keyboard=None):
        raise RuntimeError("forbidden")

    async def send_c2c(openid, content, reply_to=None, keyboard=None):
        calls.append((openid, reply_to, content))
        return SendResult(success=True, message_id="dm")

    adapter_instance._send_group_text = send_group
    adapter_instance._send_c2c_text = send_c2c

    result = await adapter_instance.send(
        "GROUP",
        "reply",
        metadata={
            "source_chat_type": "group",
            "source_chat_id": "GROUP",
            "source_user_id": "MEMBER_OK",
        },
    )

    assert result.success
    assert calls == [("MEMBER_OK", "C2C_MSG", "[群消息发送失败，改由私聊回复]\nreply")]


async def test_group_send_failure_falls_back_all_unsent_chunks(adapter_instance):
    adapter_instance._chat_type_map["GROUP"] = "group"
    adapter_instance.truncate_message = lambda text, limit: ["part 1", "part 2", "part 3"]
    group_calls = []
    dm_calls = []

    async def send_group(group_openid, content, reply_to=None, keyboard=None):
        group_calls.append((group_openid, content, reply_to))
        raise RuntimeError("forbidden")

    async def send_c2c(openid, content, reply_to=None, keyboard=None):
        dm_calls.append((openid, content, reply_to))
        return SendResult(success=True, message_id=f"dm-{len(dm_calls)}")

    adapter_instance._send_group_text = send_group
    adapter_instance._send_c2c_text = send_c2c

    result = await adapter_instance.send(
        "GROUP",
        "long reply",
        metadata={
            "source_chat_type": "group",
            "source_chat_id": "GROUP",
            "source_user_id": "MEMBER_OK",
        },
    )

    assert result.success
    assert result.message_id == "dm-3"
    assert group_calls == [("GROUP", "part 1", None)]
    assert dm_calls == [
        ("MEMBER_OK", "[群消息发送失败，改由私聊回复]\npart 1", None),
        ("MEMBER_OK", "[群消息发送失败，改由私聊回复]\npart 2", None),
        ("MEMBER_OK", "[群消息发送失败，改由私聊回复]\npart 3", None),
    ]


async def test_group_send_later_chunk_failure_falls_back_remaining_only(adapter_instance):
    adapter_instance._chat_type_map["GROUP"] = "group"
    adapter_instance.truncate_message = lambda text, limit: ["part 1", "part 2", "part 3"]
    group_calls = []
    dm_calls = []

    async def send_group(group_openid, content, reply_to=None, keyboard=None):
        group_calls.append((group_openid, content, reply_to))
        if content == "part 2":
            raise RuntimeError("forbidden")
        return SendResult(success=True, message_id=f"group-{len(group_calls)}")

    async def send_c2c(openid, content, reply_to=None, keyboard=None):
        dm_calls.append((openid, content, reply_to))
        return SendResult(success=True, message_id=f"dm-{len(dm_calls)}")

    adapter_instance._send_group_text = send_group
    adapter_instance._send_c2c_text = send_c2c

    result = await adapter_instance.send(
        "GROUP",
        "long reply",
        reply_to="GROUP_MSG",
        metadata={
            "source_chat_type": "group",
            "source_chat_id": "GROUP",
            "source_user_id": "MEMBER_OK",
        },
    )

    assert result.success
    assert result.message_id == "dm-2"
    assert group_calls == [
        ("GROUP", "part 1", "GROUP_MSG"),
        ("GROUP", "part 2", None),
    ]
    assert dm_calls == [
        ("MEMBER_OK", "[群消息发送失败，改由私聊回复]\npart 2", None),
        ("MEMBER_OK", "[群消息发送失败，改由私聊回复]\npart 3", None),
    ]


async def test_group_send_failure_uses_reply_anchor_member(adapter_instance):
    adapter_instance._chat_type_map["GROUP"] = "group"
    adapter_instance._group_last_sender["GROUP"] = "MEMBER_WRONG"
    adapter_instance._remember_group_msg_sender("GROUP_MSG", "GROUP", "MEMBER_OK")
    calls = []

    async def send_group(group_openid, content, reply_to=None, keyboard=None):
        raise RuntimeError("forbidden")

    async def send_c2c(openid, content, reply_to=None, keyboard=None):
        calls.append(openid)
        return SendResult(success=True, message_id="dm")

    adapter_instance._send_group_text = send_group
    adapter_instance._send_c2c_text = send_c2c

    result = await adapter_instance.send("GROUP", "reply", reply_to="GROUP_MSG")

    assert result.success
    assert calls == ["MEMBER_OK"]


async def test_group_send_failure_without_provenance_does_not_use_last_sender(
    adapter_instance,
):
    adapter_instance._chat_type_map["GROUP"] = "group"
    adapter_instance._group_last_sender["GROUP"] = "MEMBER_WRONG"
    calls = []

    async def send_group(group_openid, content, reply_to=None, keyboard=None):
        raise RuntimeError("forbidden")

    async def send_c2c(openid, content, reply_to=None, keyboard=None):
        calls.append(openid)
        return SendResult(success=True, message_id="wrong")

    adapter_instance._send_group_text = send_group
    adapter_instance._send_c2c_text = send_c2c

    result = await adapter_instance.send("GROUP", "reply")

    assert not result.success
    assert calls == []


async def test_ambiguous_ledger_does_not_fallback_to_last_sender(
    adapter_instance, temp_hermes_home
):
    adapter_instance._chat_type_map["GROUP"] = "group"
    adapter_instance._group_last_sender["GROUP"] = "MEMBER_WRONG"
    add_obligation(
        temp_hermes_home,
        chat_id="GROUP",
        content="reply",
        session_key="agent:main:qqbot:group:GROUP:MEMBER1",
    )
    add_obligation(
        temp_hermes_home,
        chat_id="GROUP",
        content="reply",
        session_key="agent:main:qqbot:group:GROUP:MEMBER2",
    )
    calls = []

    async def send_group(group_openid, content, reply_to=None, keyboard=None):
        raise RuntimeError("forbidden")

    async def send_c2c(openid, content, reply_to=None, keyboard=None):
        calls.append(openid)
        return SendResult(success=True, message_id="wrong")

    adapter_instance._send_group_text = send_group
    adapter_instance._send_c2c_text = send_c2c

    result = await adapter_instance.send("GROUP", "reply")

    assert not result.success
    assert calls == []


async def test_send_with_keyboard_group_failure_falls_back_to_explicit_member(
    adapter_instance,
):
    adapter_instance._chat_type_map["GROUP"] = "group"
    calls = []

    async def send_group(group_openid, content, reply_to=None, keyboard=None):
        raise RuntimeError("keyboard denied")

    async def send_c2c(openid, content, reply_to=None, keyboard=None):
        calls.append((openid, content))
        return SendResult(success=True, message_id="dm")

    adapter_instance._send_group_text = send_group
    adapter_instance._send_c2c_text = send_c2c

    result = await adapter_instance.send_with_keyboard(
        "GROUP",
        "approve?",
        keyboard=object(),
        fallback_member_openid="MEMBER_OK",
    )

    assert result.success
    assert calls == [("MEMBER_OK", "[群消息发送失败，改由私聊回复]\napprove?")]


async def test_send_exec_approval_uses_group_msg_id_and_session_member_for_fallback(
    adapter_instance,
):
    captured = {}
    adapter_instance._last_msg_id["GROUP"] = "GROUP_MSG"
    adapter_instance._last_msg_id["MEMBER_OK"] = "C2C_MSG"
    adapter_instance._last_msg_id_ts["MEMBER_OK"] = time.time()

    async def fake_send_approval(
        chat_id,
        req,
        reply_to=None,
        *,
        fallback_member_openid=None,
        allow_legacy_fallback=True,
    ):
        captured.update(
            chat_id=chat_id,
            reply_to=reply_to,
            fallback_member_openid=fallback_member_openid,
            allow_legacy_fallback=allow_legacy_fallback,
            session_key=req.session_key,
        )
        return SendResult(success=True, message_id="approval")

    adapter_instance.send_approval_request = fake_send_approval

    result = await adapter_instance.send_exec_approval(
        chat_id="GROUP",
        command="rm -rf /tmp/demo",
        session_key="agent:main:qqbot:group:GROUP:MEMBER_OK",
        description="delete temp dir",
    )

    assert result.success
    assert captured == {
        "chat_id": "GROUP",
        "reply_to": "GROUP_MSG",
        "fallback_member_openid": "MEMBER_OK",
        "allow_legacy_fallback": False,
        "session_key": "agent:main:qqbot:group:GROUP:MEMBER_OK",
    }


async def test_send_exec_approval_accepts_old_send_approval_override(adapter_instance):
    calls = []

    async def old_send_approval(chat_id, req, reply_to=None):
        calls.append((chat_id, req.session_key, reply_to))
        return SendResult(success=True, message_id="approval")

    adapter_instance.send_approval_request = old_send_approval
    adapter_instance._last_msg_id["user-1"] = "inbound-42"

    result = await adapter_instance.send_exec_approval(
        chat_id="user-1",
        command="rm -rf /tmp/demo",
        session_key="sess:abc",
        description="delete temp dir",
    )

    assert result.success
    assert calls == [("user-1", "sess:abc", "inbound-42")]


async def test_send_update_prompt_preserves_session_member_for_group_fallback(
    adapter_instance,
):
    captured = {}
    adapter_instance._last_msg_id["GROUP"] = "GROUP_MSG"

    async def fake_send_with_keyboard(
        chat_id,
        content,
        keyboard,
        reply_to=None,
        *,
        fallback_member_openid=None,
        allow_legacy_fallback=True,
    ):
        captured.update(
            chat_id=chat_id,
            content=content,
            reply_to=reply_to,
            fallback_member_openid=fallback_member_openid,
            allow_legacy_fallback=allow_legacy_fallback,
        )
        return SendResult(success=True, message_id="update")

    adapter_instance.send_with_keyboard = fake_send_with_keyboard

    result = await adapter_instance.send_update_prompt(
        chat_id="GROUP",
        prompt="Continue?",
        default="y",
        session_key="agent:main:qqbot:group:GROUP:MEMBER_OK",
    )

    assert result.success
    assert captured["chat_id"] == "GROUP"
    assert "Continue?" in captured["content"]
    assert captured["reply_to"] == "GROUP_MSG"
    assert captured["fallback_member_openid"] == "MEMBER_OK"
    assert captured["allow_legacy_fallback"] is False


async def test_send_update_prompt_accepts_old_send_with_keyboard_override(adapter_instance):
    captured = {}

    async def old_send_with_keyboard(chat_id, content, keyboard, reply_to=None):
        captured.update(chat_id=chat_id, content=content, reply_to=reply_to)
        return SendResult(success=True, message_id="update")

    adapter_instance.send_with_keyboard = old_send_with_keyboard
    adapter_instance._last_msg_id["u1"] = "prev-msg"

    result = await adapter_instance.send_update_prompt(
        chat_id="u1",
        prompt="Continue?",
        default="n",
        session_key="ignored",
        metadata={"x": 1},
    )

    assert result.success
    assert captured["reply_to"] == "prev-msg"
    assert "default: n" in captured["content"]


async def test_media_quota_fallback_removes_msg_id_and_changes_msg_seq(adapter_instance):
    adapter_instance._chat_type_map["USER"] = "c2c"
    adapter_instance._next_msg_seq = lambda key: 100 + len(api_calls)
    adapter_instance._upload_media = AsyncMock(return_value={"file_info": "FILE_INFO"})
    api_calls = []

    async def api_request(method, path, body):
        api_calls.append((method, path, dict(body)))
        if len(api_calls) == 1:
            raise RuntimeError(PASSIVE_QUOTA_ERROR)
        return {"id": "media-msg"}

    adapter_instance._api_request = api_request

    result = await adapter_instance._send_media(
        "USER",
        "https://example.com/image.png",
        file_type=1,
        kind="image",
        caption="caption",
        reply_to="MSG1",
    )

    assert result.success
    assert [call[1] for call in api_calls] == [
        "/v2/users/USER/messages",
        "/v2/users/USER/messages",
    ]
    assert api_calls[0][2]["msg_id"] == "MSG1"
    assert "msg_id" not in api_calls[1][2]
    assert api_calls[0][2]["msg_seq"] != api_calls[1][2]["msg_seq"]
