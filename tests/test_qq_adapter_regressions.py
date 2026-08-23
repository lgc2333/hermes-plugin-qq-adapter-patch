from gateway.platforms.base import SendResult

from conftest import add_obligation


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
