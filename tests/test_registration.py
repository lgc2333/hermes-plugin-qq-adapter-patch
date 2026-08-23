from gateway.config import PlatformConfig


class DummyContext:
    def __init__(self):
        self.platforms = []

    def register_platform(self, **kwargs):
        self.platforms.append(kwargs)


def test_register_replaces_qqbot_platform(adapter_module):
    ctx = DummyContext()
    adapter_module.register(ctx)

    assert len(ctx.platforms) == 1
    entry = ctx.platforms[0]
    assert entry["name"] == "qqbot"
    assert entry["label"] == "QQ Bot adapter patch (fork)"
    assert entry["required_env"] == ["QQ_APP_ID", "QQ_CLIENT_SECRET"]
    assert callable(entry["adapter_factory"])
    assert callable(entry["check_fn"])

    adapter = entry["adapter_factory"](PlatformConfig(enabled=True))
    assert isinstance(adapter, adapter_module.QQAdapterPatchAdapter)
