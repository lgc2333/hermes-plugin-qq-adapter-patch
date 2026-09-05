"""group_member_allow_from 成员级白名单 + env 兜底的回归测试。"""

import asyncio
import logging

import pytest
from gateway.config import PlatformConfig

from conftest import load_adapter_module


def _make_adapter(adapter_module, extra, monkeypatch, env=None):
    for name in (
        "QQ_GROUP_ALLOW_FROM",
        "QQ_GROUP_MEMBER_ALLOW_FROM",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in (env or {}).items():
        monkeypatch.setenv(name, value)
    return adapter_module.QQAdapter(
        PlatformConfig(enabled=True, extra={"app_id": "a", "client_secret": "b", **extra})
    )


def test_member_allowlist_accepts_listed_member(adapter_module, monkeypatch):
    adapter = _make_adapter(
        adapter_module,
        {
            "group_policy": "allowlist",
            "group_allow_from": ["GROUP"],
            "group_member_allow_from": [" MEMBER1 "],
        },
        monkeypatch,
    )

    assert adapter._group_member_allow_from == ["MEMBER1"]
    assert adapter._is_group_allowed("GROUP", "member1") is True


def test_member_allowlist_rejects_unlisted_member(adapter_module, monkeypatch):
    adapter = _make_adapter(
        adapter_module,
        {
            "group_policy": "allowlist",
            "group_allow_from": ["GROUP"],
            "group_member_allow_from": ["MEMBER1"],
        },
        monkeypatch,
    )

    assert adapter._group_acl_reject_reason("GROUP", "MEMBER2") == (
        "member_not_in_allowlist"
    )
    assert adapter._is_group_allowed("GROUP", "MEMBER2") is False


def test_member_allowlist_empty_list_allows_any_member(adapter_module, monkeypatch):
    adapter = _make_adapter(
        adapter_module,
        {
            "group_policy": "allowlist",
            "group_allow_from": ["GROUP"],
            "group_member_allow_from": [],
        },
        monkeypatch,
    )

    assert adapter._is_group_allowed("GROUP", "ANY_MEMBER") is True


def test_member_allowlist_wildcard_member(adapter_module, monkeypatch):
    adapter = _make_adapter(
        adapter_module,
        {
            "group_policy": "allowlist",
            "group_allow_from": ["GROUP"],
            "group_member_allow_from": ["*"],
        },
        monkeypatch,
    )

    assert adapter._is_group_allowed("GROUP", "ANY_MEMBER") is True


def test_member_allowlist_reads_env_fallback(adapter_module, monkeypatch):
    adapter = _make_adapter(
        adapter_module,
        {
            "group_policy": "allowlist",
            "group_allow_from": ["GROUP"],
        },
        monkeypatch,
        env={"QQ_GROUP_MEMBER_ALLOW_FROM": "MEMBER1, MEMBER2"},
    )

    assert adapter._group_member_allow_from == ["MEMBER1", "MEMBER2"]
    assert adapter._is_group_allowed("GROUP", "MEMBER2") is True
    assert adapter._is_group_allowed("GROUP", "MEMBER3") is False


def test_group_allow_reads_env_fallback(adapter_module, monkeypatch):
    adapter = _make_adapter(
        adapter_module,
        {"group_policy": "allowlist"},
        monkeypatch,
        env={"QQ_GROUP_ALLOW_FROM": "GROUP_A , GROUP_B"},
    )

    assert adapter._group_allow_from == ["GROUP_A", "GROUP_B"]
    assert adapter._is_group_allowed("GROUP_B", "MEMBER") is True
    assert adapter._is_group_allowed("GROUP_C", "MEMBER") is False


def test_extra_wins_over_env(adapter_module, monkeypatch):
    monkeypatch.setenv("QQ_GROUP_ALLOW_FROM", "ENV_GROUP")
    monkeypatch.setenv("QQ_GROUP_MEMBER_ALLOW_FROM", "ENV_MEMBER")
    adapter = _make_adapter(
        adapter_module,
        {
            "group_policy": "allowlist",
            "group_allow_from": ["EXTRA_GROUP"],
            "group_member_allow_from": ["EXTRA_MEMBER"],
        },
        monkeypatch,
    )

    assert adapter._group_allow_from == ["EXTRA_GROUP"]
    assert adapter._group_member_allow_from == ["EXTRA_MEMBER"]
    assert adapter._is_group_allowed("EXTRA_GROUP", "EXTRA_MEMBER") is True
    assert adapter._is_group_allowed("ENV_GROUP", "EXTRA_MEMBER") is False


def test_member_filter_applies_under_open_policy(adapter_module, monkeypatch):
    adapter = _make_adapter(
        adapter_module,
        {
            "group_policy": "open",
            "group_member_allow_from": ["MEMBER1"],
        },
        monkeypatch,
    )

    assert adapter._is_group_allowed("ANY_GROUP", "MEMBER1") is True
    assert adapter._group_acl_reject_reason("ANY_GROUP", "MEMBER2") == (
        "member_not_in_allowlist"
    )


def test_guild_check_skips_member_table(adapter_module, monkeypatch):
    adapter = _make_adapter(
        adapter_module,
        {
            "group_policy": "allowlist",
            "group_allow_from": ["GUILD_ID"],
            "group_member_allow_from": ["MEMBER1"],
        },
        monkeypatch,
    )

    assert adapter._is_group_allowed("GUILD_ID", "SOMEONE_ELSE", check_member=False) is True
    # 同参数下群路径会因成员表拒绝，证明 check_member 确实生效
    assert adapter._is_group_allowed("GUILD_ID", "SOMEONE_ELSE") is False


def test_group_allow_defaults_to_empty_list(adapter_module, monkeypatch):
    """extra 和 env 都未配置时，群白名单默认空列表。"""
    adapter = _make_adapter(adapter_module, {"group_policy": "allowlist"}, monkeypatch)

    assert adapter._group_allow_from == []
    assert adapter._group_member_allow_from == []


def test_default_empty_group_list_rejects_all_groups(adapter_module, monkeypatch):
    """allowlist + 未配置群白名单 → 所有群拒绝（fail-closed），成员表不救。"""
    adapter = _make_adapter(adapter_module, {"group_policy": "allowlist"}, monkeypatch)

    assert adapter._group_acl_reject_reason("ANY_GROUP", "MEMBER") == (
        "group_not_in_allowlist"
    )
    assert adapter._is_group_allowed("ANY_GROUP", "MEMBER") is False


def test_absent_member_list_allows_any_member(adapter_module, monkeypatch):
    """group_member_allow_from 在 extra 和 env 都彻底未配置 → 任何成员放行。"""
    adapter = _make_adapter(
        adapter_module,
        {
            "group_policy": "allowlist",
            "group_allow_from": ["GROUP"],
        },
        monkeypatch,
    )

    assert adapter._group_member_allow_from == []
    assert adapter._is_group_allowed("GROUP", "MEMBER_A") is True
    assert adapter._is_group_allowed("GROUP", "MEMBER_B") is True


def test_group_gate_evaluated_before_member_gate(adapter_module, monkeypatch):
    """两道门按群→成员顺序判定：群未放行时 reason 恒为群级，即使成员也不在表。"""
    adapter = _make_adapter(
        adapter_module,
        {
            "group_policy": "allowlist",
            "group_allow_from": ["GOOD_GROUP"],
            "group_member_allow_from": ["MEMBER1"],
        },
        monkeypatch,
    )

    # 群不在白名单 + 成员也不在表 → 只报群级原因（群门在前）
    assert adapter._group_acl_reject_reason("BAD_GROUP", "STRANGER") == (
        "group_not_in_allowlist"
    )
    # 群放行后才轮到成员门
    assert adapter._group_acl_reject_reason("GOOD_GROUP", "STRANGER") == (
        "member_not_in_allowlist"
    )
    assert adapter._group_acl_reject_reason("GOOD_GROUP", "MEMBER1") is None


def test_reject_log_includes_reason(adapter_module, monkeypatch, caplog):
    adapter = _make_adapter(
        adapter_module,
        {
            "group_policy": "allowlist",
            "group_allow_from": ["GROUP"],
            "group_member_allow_from": ["MEMBER1"],
        },
        monkeypatch,
    )
    adapter._chat_type_map = {}
    adapter._message_handler = None

    with caplog.at_level(logging.INFO):
        asyncio.run(
            adapter._handle_group_message(
                {"group_openid": "GROUP", "attachments": None},
                "MSG1",
                "hello",
                {"member_openid": "STRANGER"},
                "",
            )
        )

    assert "member_not_in_allowlist" in caplog.text
    assert "STRANGER" in caplog.text
    assert "hello" in caplog.text
