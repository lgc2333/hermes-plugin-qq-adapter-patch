"""上游契约回归：审批按钮必须走 base 模板 + `_send_exec_approval_prompt` 钩子。

背景（上游 2026-09-13 `ad305bea`）：runner 不再用 `hasattr(type(adapter),
"send_exec_approval")` 探测按钮能力（那句话对每个适配器都为真），改成
`supports_exec_approval_buttons()` —— 它只认 `_send_exec_approval_prompt` 是否被覆写。
fork 当时覆写的还是旧的 `send_exec_approval`，于是探测恒为 False：QQ 的审批键盘被
静默禁用，用户只收到纯文本 /approve 回退。

另附 `_open_dm_opted_in` 的作用域回归（上游 cbd03e6e）：opt-in 必须按 profile
作用域读取，不能被默认 profile 的裸 os.environ 打开/遮挡。
"""

from gateway.platforms.base import BasePlatformAdapter, ExecApprovalPrompt, SendResult


def _prompt(actions=None, smart_denied=False, chat_id="GROUP"):
    return ExecApprovalPrompt(
        chat_id=chat_id,
        session_key="agent:main:qqbot:group:G:U",
        text="(shared text)",
        actions=actions if actions is not None else [
            ("Allow once", "once", "primary"),
            ("Allow always", "always", ""),
            ("Deny", "deny", "danger"),
        ],
        command="rm -rf /tmp/x",
        description="dangerous command",
        smart_denied=smart_denied,
    )


class TestExecApprovalContract:
    def test_approval_uses_the_base_template(self, adapter_module):
        # 覆写钩子而不是旧方法：探测为 True，且 gateway 调用的仍是基类模板。
        assert adapter_module.QQAdapter.send_exec_approval is (
            BasePlatformAdapter.send_exec_approval
        )
        assert adapter_module.QQAdapter.supports_exec_approval_buttons() is True

    async def test_prompt_sends_keyboard_with_reply_anchor(
        self, adapter_module, adapter_instance
    ):
        sent = {}

        async def fake_send_with_keyboard(chat_id, content, keyboard, reply_to=None):
            sent.update(
                chat_id=chat_id, content=content, keyboard=keyboard, reply_to=reply_to
            )
            return SendResult(success=True, message_id="m1")

        adapter_instance.send_with_keyboard = fake_send_with_keyboard
        adapter_instance._last_msg_id = {"GROUP": "INBOUND_MSG"}

        result = await adapter_instance._send_exec_approval_prompt(_prompt())

        assert result.success is True
        assert sent["chat_id"] == "GROUP"
        assert sent["reply_to"] == "INBOUND_MSG"
        assert sent["keyboard"] is not None
        assert "rm -rf /tmp/x" in sent["content"]

    async def test_prompt_without_inbound_anchor_sends_active(
        self, adapter_module, adapter_instance
    ):
        sent = {}

        async def fake_send_with_keyboard(chat_id, content, keyboard, reply_to=None):
            sent.update(reply_to=reply_to)
            return SendResult(success=True, message_id="m1")

        adapter_instance.send_with_keyboard = fake_send_with_keyboard
        adapter_instance._last_msg_id = {}

        await adapter_instance._send_exec_approval_prompt(_prompt())

        assert sent["reply_to"] is None

    async def test_always_button_follows_the_prompt_choices(
        self, adapter_module, adapter_instance, monkeypatch
    ):
        captured = {}

        def fake_keyboard(session_key, *, allow_permanent=True):
            captured["allow_permanent"] = allow_permanent
            return object()

        async def fake_send_with_keyboard(chat_id, content, keyboard, reply_to=None):
            return SendResult(success=True, message_id="m1")

        monkeypatch.setattr(adapter_module, "build_approval_keyboard", fake_keyboard)
        adapter_instance.send_with_keyboard = fake_send_with_keyboard

        await adapter_instance._send_exec_approval_prompt(_prompt())
        assert captured["allow_permanent"] is True

        await adapter_instance._send_exec_approval_prompt(
            _prompt(
                actions=[("Allow once", "once", ""), ("Deny", "deny", "")],
                smart_denied=True,
            )
        )
        assert captured["allow_permanent"] is False


class TestOptInScope:
    """cbd03e6e：opt-in 只能按 profile 作用域读取。

    fork 不再自带 `_open_dm_opted_in` —— 上游把它移进了
    `OwnAccessPolicyMixin`，并且已经用作用域读取器实现（本 fork 无需再打补丁）。
    下面两条钉住"用的是 mixin 的作用域实现、且两个 env 名都经它读取"。
    """

    def test_adapter_does_not_shadow_the_scoped_mixin_reader(self, adapter_module):
        from gateway.platforms.access_policy_mixin import OwnAccessPolicyMixin

        assert (
            adapter_module.QQAdapter._open_dm_opted_in
            is OwnAccessPolicyMixin._open_dm_opted_in
        )

    def test_unscoped_env_does_not_open_intake(
        self, adapter_instance, monkeypatch
    ):
        import gateway.platforms.access_policy_mixin as mixin

        monkeypatch.setenv("GATEWAY_ALLOW_ALL_USERS", "true")
        monkeypatch.setattr(mixin, "get_scoped_secret", lambda name, default="": "")

        assert adapter_instance._open_dm_opted_in() is False

    def test_both_names_are_read_through_the_scoped_reader(
        self, adapter_instance, monkeypatch
    ):
        import gateway.platforms.access_policy_mixin as mixin

        seen = []

        def fake_scoped(name, default=""):
            seen.append(name)
            return "YES" if name == "QQ_ALLOW_ALL_USERS" else ""

        monkeypatch.setattr(mixin, "get_scoped_secret", fake_scoped)

        assert adapter_instance._open_dm_opted_in() is True
        assert seen == ["GATEWAY_ALLOW_ALL_USERS", "QQ_ALLOW_ALL_USERS"]
