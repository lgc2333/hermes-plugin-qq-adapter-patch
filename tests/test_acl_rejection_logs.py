"""Intake ACL 拒绝日志回归测试：拒绝时必须能从日志拿到 ID 与消息内容。"""

import logging

async def test_group_acl_rejection_logs_ids_and_content(adapter_instance, caplog):
    adapter_instance._group_policy = "allowlist"
    adapter_instance._group_allow_from = ["GOOD_GROUP"]

    with caplog.at_level(logging.INFO):
        await adapter_instance._handle_group_message(
            {"group_openid": "BAD_GROUP", "attachments": None},
            "MSG1",
            "hello world",
            {"member_openid": "MEMBER_X"},
            "",
        )

    text = caplog.text
    assert "rejected by ACL" in text
    assert "BAD_GROUP" in text
    assert "MEMBER_X" in text
    assert "hello world" in text


async def test_c2c_acl_rejection_logs_user_and_content(adapter_instance, caplog):
    adapter_instance._dm_policy = "allowlist"
    adapter_instance._allow_from = []

    with caplog.at_level(logging.INFO):
        await adapter_instance._handle_c2c_message(
            {"attachments": None},
            "MSG2",
            "dm text",
            {"user_openid": "USER_X"},
            "",
        )

    text = caplog.text
    assert "rejected by ACL" in text
    assert "USER_X" in text
    assert "dm text" in text


async def test_allowed_group_message_not_logged_as_rejected(
    adapter_instance, caplog
):
    adapter_instance._group_policy = "allowlist"
    adapter_instance._group_allow_from = ["GOOD_GROUP"]

    with caplog.at_level(logging.INFO):
        await adapter_instance._handle_group_message(
            {"group_openid": "GOOD_GROUP", "attachments": None},
            "MSG3",
            "hi",
            {"member_openid": "MEMBER_Y"},
            "",
        )

    assert "rejected by ACL" not in caplog.text
