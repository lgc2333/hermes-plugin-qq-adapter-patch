"""2026-09-05 群→私聊 fallback 漏消息事故的回归测试。

事故（session 20260905_172410_2d9ff5a7，gateway.log 17:25–17:35）：
群被动回复额度用完后，后续群发全部报 ``主动消息失败, 无权限``。
``send()`` 只有在 metadata / reply_to 锚点 / delivery ledger 三者之一
能解析出成员时才私聊 fallback；中途进度类消息三者皆无，被静默丢弃
（17:32–17:35 共 8 条 ``no known sender — cannot fall back to DM``）。
图片本体 17:35:34 群发失败后也没有任何私聊补发。

修复约定（用户已确认）：
- 文本：三级溯源全空时，若该群近 5 分钟只有唯一活跃 sender，
  允许按该成员私聊 fallback（并发多用户风险由唯一性约束挡住）；
- 媒体：群发失败走同一成员解析逻辑，补发到私聊。
"""

import time
from unittest.mock import AsyncMock

import pytest
from gateway.config import PlatformConfig
from gateway.platforms.base import SendResult

GROUP_RATE_LIMIT_ERROR = (
    "QQ Bot API error [400] /v2/groups/GROUP/messages: 主动消息失败, 无权限"
)
DM_PREFIX = "[群消息发送失败，改由私聊回复]\n"


def _wire_rate_limited_group(adapter_instance, group_calls, dm_calls):
    """群发恒报「主动消息失败, 无权限」，私聊调用记入 dm_calls。"""
    adapter_instance._chat_type_map["GROUP"] = "group"
    # 真实场景里用户 5 分钟前刚在群里触发过任务，last-sender 一定有值
    adapter_instance._group_last_sender["GROUP"] = "MEMBER"

    async def send_group(group_openid, content, reply_to=None, keyboard=None):
        group_calls.append(("group", group_openid, reply_to, content))
        raise RuntimeError(GROUP_RATE_LIMIT_ERROR)

    async def send_c2c(openid, content, reply_to=None, keyboard=None):
        dm_calls.append(("c2c", openid, reply_to, content))
        return SendResult(success=True, message_id="dm")

    adapter_instance._send_group_text = send_group
    adapter_instance._send_c2c_text = send_c2c


async def test_rate_limited_group_with_reply_anchor_still_falls_back_to_dm(
    adapter_instance, temp_hermes_home
):
    """17:31 的成功路径：群 msg_id 在 5 分钟窗口内 → 锚点解析出成员 → 私聊。"""
    group_calls, dm_calls = [], []
    _wire_rate_limited_group(adapter_instance, group_calls, dm_calls)
    adapter_instance._last_msg_id["GROUP"] = "TRIG_MSG"
    adapter_instance._last_msg_id_ts["GROUP"] = time.time() - 60
    adapter_instance._remember_group_msg_sender("TRIG_MSG", "GROUP", "MEMBER")

    result = await adapter_instance.send("GROUP", "WeasyPrint 就绪。")

    assert result.success
    assert dm_calls == [("c2c", "MEMBER", None, DM_PREFIX + "WeasyPrint 就绪。")]


async def test_rate_limited_group_sole_recent_sender_falls_back_to_dm(
    adapter_instance, temp_hermes_home
):
    """修复 17:32–17:35 漏消息：无 metadata/锚点/ledger 时，唯一近期 sender 兜底私聊。

    中途进度消息不写 ledger、gateway 不传 metadata、群 msg_id 超出 5 分钟
    被动窗口——修复前这类消息被静默丢弃（8 条全丢）；修复后按群里唯一
    活跃 sender 私聊补发。
    """
    group_calls, dm_calls = [], []
    _wire_rate_limited_group(adapter_instance, group_calls, dm_calls)
    adapter_instance._remember_recent_group_sender("GROUP", "MEMBER")

    result = await adapter_instance.send("GROUP", "Working — iteration 6/500")

    assert result.success
    assert len(group_calls) == 3  # 群内退避重试后仍失败，才走私聊
    assert dm_calls == [
        ("c2c", "MEMBER", None, DM_PREFIX + "Working — iteration 6/500")
    ]


async def test_rate_limited_group_two_recent_senders_no_dm_fallback(
    adapter_instance, temp_hermes_home
):
    """唯一性约束：近 5 分钟有多个活跃 sender 时不私聊（防把 A 的回复发给 B）。"""
    group_calls, dm_calls = [], []
    _wire_rate_limited_group(adapter_instance, group_calls, dm_calls)
    adapter_instance._remember_recent_group_sender("GROUP", "MEMBER_A")
    adapter_instance._remember_recent_group_sender("GROUP", "MEMBER_B")

    result = await adapter_instance.send("GROUP", "reply")

    assert not result.success
    assert dm_calls == []


async def test_fallback_window_outlives_qq_passive_reply_window(
    adapter_instance, temp_hermes_home
):
    """窗口回归：发言人 10 分钟前入站（超出 QQ 5 分钟被动窗口）仍可兜底。

    事故里最后一次入站是 17:25:47，17:32–17:35 的消息距它 7–10 分钟——
    若收件人窗口镜像 QQ 被动窗口（300s），这些消息依然会丢。
    """
    group_calls, dm_calls = [], []
    _wire_rate_limited_group(adapter_instance, group_calls, dm_calls)
    ts = time.time()
    adapter_instance._group_recent_senders["GROUP"] = {"MEMBER": ts - 600}

    result = await adapter_instance.send("GROUP", "late progress")

    assert result.success
    assert dm_calls == [("c2c", "MEMBER", None, DM_PREFIX + "late progress")]


async def test_fallback_window_expired_speaker_not_used(
    adapter_instance, temp_hermes_home
):
    """发言人超出会话新鲜度窗口（默认 2h）后不再兜底。"""
    group_calls, dm_calls = [], []
    _wire_rate_limited_group(adapter_instance, group_calls, dm_calls)
    adapter_instance._group_recent_senders["GROUP"] = {
        "MEMBER": time.time() - 7201
    }

    result = await adapter_instance.send("GROUP", "very late reply")

    assert not result.success
    assert dm_calls == []


async def test_rate_limited_group_media_failure_falls_back_to_dm(
    adapter_instance,
):
    """修复 17:35:34 漏图：媒体群发失败后按唯一近期 sender 私聊补发。"""
    adapter_instance._chat_type_map["GROUP"] = "group"
    adapter_instance._remember_recent_group_sender("GROUP", "MEMBER")
    adapter_instance._next_msg_seq = lambda key: 1
    adapter_instance._upload_local_file = AsyncMock(
        return_value=("long.png", {"file_info": "FILE_INFO"})
    )
    api_calls = []

    async def api_request(method, path, body):
        api_calls.append((method, path, dict(body)))
        if "/v2/groups/" in path:
            raise RuntimeError(GROUP_RATE_LIMIT_ERROR)
        return {"id": "dm-media"}

    adapter_instance._api_request = api_request

    result = await adapter_instance._send_media(
        "GROUP",
        "/tmp/long.png",
        file_type=1,
        kind="image",
        caption="整页长图",
    )

    assert result.success
    assert [call[1] for call in api_calls] == [
        "/v2/groups/GROUP/messages",
        "/v2/users/MEMBER/messages",
    ]
    dm_body = api_calls[1][2]
    dm_text = dm_body.get("content") or dm_body.get("markdown", {}).get("content")
    assert dm_text == DM_PREFIX + "整页长图\n[原始文件] /tmp/long.png"


async def test_rate_limited_group_media_failure_two_senders_no_fallback(
    adapter_instance,
):
    """唯一性约束同样适用于媒体：多活跃 sender 时不私聊补发。"""
    adapter_instance._chat_type_map["GROUP"] = "group"
    adapter_instance._remember_recent_group_sender("GROUP", "MEMBER_A")
    adapter_instance._remember_recent_group_sender("GROUP", "MEMBER_B")
    adapter_instance._next_msg_seq = lambda key: 1
    adapter_instance._upload_local_file = AsyncMock(
        return_value=("long.png", {"file_info": "FILE_INFO"})
    )

    async def api_request(method, path, body):
        raise RuntimeError(GROUP_RATE_LIMIT_ERROR)

    adapter_instance._api_request = api_request

    result = await adapter_instance._send_media(
        "GROUP", "/tmp/long.png", file_type=1, kind="image", caption="整页长图"
    )

    assert not result.success
    assert "主动消息失败" in (result.error or "")
