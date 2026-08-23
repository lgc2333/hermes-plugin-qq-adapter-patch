from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_manifest_declares_platform_plugin():
    manifest = yaml.safe_load((ROOT / "plugin.yaml").read_text(encoding="utf-8"))
    assert manifest["name"] == "qq-adapter-patch"
    assert manifest["kind"] == "platform"
    assert manifest["version"]
    assert {item["name"] for item in manifest["requires_env"]} == {
        "QQ_APP_ID",
        "QQ_CLIENT_SECRET",
    }


def test_plugin_exports_register():
    init_text = (ROOT / "__init__.py").read_text(encoding="utf-8")
    assert "register" in init_text
