from __future__ import annotations

import importlib.util
import sqlite3
import sys
import types
from pathlib import Path

import pytest

from gateway.config import Platform


REPO_ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = REPO_ROOT / "adapter.py"


def load_adapter_module():
    spec = importlib.util.spec_from_file_location("qq_adapter_patch_test", ADAPTER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def adapter_module():
    return load_adapter_module()


@pytest.fixture()
def adapter_instance(adapter_module):
    adapter = object.__new__(adapter_module.QQAdapter)
    adapter.platform = Platform.QQBOT
    adapter._message_handler = None
    adapter._app_id = "test-app"
    adapter._chat_type_map = {}
    adapter._group_last_sender = {}
    adapter._group_msg_sender = {}
    adapter._group_msg_sender_ttl = 86400
    adapter._group_msg_sender_max = 1000
    adapter._group_recent_senders = {}
    adapter._group_recent_sender_window = 7200.0
    adapter._last_msg_id = {}
    adapter._last_msg_id_ts = {}
    adapter._running = True
    adapter._ws = types.SimpleNamespace(closed=False)
    adapter._http_client = types.SimpleNamespace(put=None)
    adapter._markdown_support = True
    adapter._dm_policy = "pairing"
    adapter._allow_from = []
    adapter._group_policy = "allowlist"
    adapter._group_allow_from = ["GROUP"]
    adapter._group_member_allow_from = []
    adapter._seen_messages = {}
    adapter._upload_cache = {}
    adapter.MAX_MESSAGE_LENGTH = 4000
    adapter.format_message = lambda text: text
    adapter.truncate_message = lambda text, limit: [text]
    return adapter


@pytest.fixture()
def temp_hermes_home(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE delivery_obligations ("
            "platform TEXT, chat_id TEXT, content TEXT, state TEXT, "
            "session_key TEXT, updated_at REAL)"
        )
    import hermes_constants

    monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: tmp_path)
    return tmp_path


def add_obligation(home: Path, *, chat_id: str, content: str, session_key: str, state: str = "pending"):
    with sqlite3.connect(home / "state.db") as conn:
        conn.execute(
            "INSERT INTO delivery_obligations "
            "(platform, chat_id, content, state, session_key, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("qqbot", chat_id, content, state, session_key, 1.0),
        )
