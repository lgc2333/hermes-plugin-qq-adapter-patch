# Hermes QQ Adapter Patch

Hermes directory plugin for the official QQ Bot adapter.

This plugin registers platform `qqbot` and replaces Hermes' built-in QQ adapter at runtime. It carries local fixes for QQ group/private delivery behavior.

## What is patched

Visible behavior this fork changes:

- **Long replies are no longer lost.** QQ only lets a bot reply "in thread" to your message for a limited time (5 minutes in groups, 60 in private chats) and for a limited number of replies. Once that lapses, the plugin now sends the same message as a standalone message instead of retrying a reference that can never work and dropping the reply. Text, approval/confirmation buttons, and images/voice/video/files all behave this way.
- **Approval and confirmation buttons work under a named profile.** They used to be rejected as unauthorized: clicking did nothing and the approval timed out.
- **Per-member allowlist inside a group.** Besides allowing whole groups, you can restrict which members are allowed to trigger the bot.
- **Rejected messages are logged** with sender, chat openid, the policy that rejected them and the original text, so you can find the openids to allowlist.

## Compatibility

This is not a standalone Python app. It depends on Hermes runtime modules such as `gateway.*` and `gateway.platforms.qqbot.*`.

Tested against the local Hermes source layout where QQ adapter support is available under:

```text
gateway/platforms/qqbot/
```

## Install

Use the active profile's `HERMES_HOME`. Do not hardcode `~/.hermes`.

1. Copy the directory plugin:

```bash
mkdir -p "$HERMES_HOME/plugins"
cp -R qq-adapter-patch "$HERMES_HOME/plugins/qq-adapter-patch"
```

2. Enable it:

```bash
hermes plugins enable qq-adapter-patch
```

3. Check it:

```bash
hermes plugins doctor "$HERMES_HOME/plugins/qq-adapter-patch"
hermes plugins list --enabled
```

4. Restart the gateway or the Hermes process that loads platforms.

## Extra configuration

Group ACL in the QQ platform config (`platforms.qqbot.extra` in `config.yaml`):

```yaml
group_policy: "allowlist"        # open | allowlist | disabled | pairing
group_allow_from:                # group_openid allowlist (empty = reject all under allowlist)
  - "group_openid_1"
group_member_allow_from:         # optional member_openid filter inside allowed groups
  - "member_openid_1"            # empty / absent = any member
```

Env equivalents (used only when the corresponding `extra` key is absent):

```text
QQ_GROUP_ALLOW_FROM=group_openid_1,group_openid_2
QQ_GROUP_MEMBER_ALLOW_FROM=member_openid_1,member_openid_2
```

Notes:

- `group_policy` and `dm_policy` have no env spelling; set them in `config.yaml`.
- `*` wildcards are honored in both allowlists.
- Rejected messages are logged at INFO with the group/member openid, reason
  (`group_not_in_allowlist` / `member_not_in_allowlist` / ...), policy and raw
  content — use the log to discover openids for your allowlist.

## Tests

The plugin's own tests need pytest, pytest-asyncio and the runtime deps the Hermes gateway package imports. A minimal venv works:

```bash
uv venv /tmp/qq-test-venv --python 3.13
uv pip install --python /tmp/qq-test-venv/bin/python pytest pytest-asyncio pyyaml aiohttp httpx websockets
```

Then, from this repo:

```bash
PYTHONPATH=/opt/hermes:$PWD /tmp/qq-test-venv/bin/python -m pytest tests -q
```

`/opt/hermes/.venv` cannot run these tests: it is root-owned and ships no pytest.

CI checks out Hermes `main` **unpinned** on purpose, so an upstream change that breaks this fork shows up in CI. Reproduce that step locally instead of pushing to find out:

```bash
mkdir -p /tmp/ci/tests/gateway && rm -rf /tmp/ci/gateway && cp -a /opt/hermes/gateway /tmp/ci/gateway
cp adapter.py /tmp/ci/gateway/platforms/qqbot/adapter.py
for f in test_qqbot.py test_qqbot_credential_isolation.py test_qqbot_scope_paths.py conftest.py; do
  gh api -H "Accept: application/vnd.github.raw" "repos/NousResearch/hermes-agent/contents/tests/gateway/$f?ref=main" > "/tmp/ci/tests/gateway/$f"
done
gh api -H "Accept: application/vnd.github.raw" "repos/NousResearch/hermes-agent/contents/tests/conftest.py?ref=main" > /tmp/ci/tests/conftest.py
cd /tmp/ci && PYTHONPATH=/tmp/ci:/opt/hermes /tmp/qq-test-venv/bin/python -m pytest tests/gateway/test_qqbot.py tests/gateway/test_qqbot_credential_isolation.py tests/gateway/test_qqbot_scope_paths.py -q -o asyncio_mode=auto
```

The overlay order matters: `/tmp/ci` must come first on `PYTHONPATH` so `gateway.platforms.qqbot.adapter` resolves to the copy with this plugin's `adapter.py`. The `rm -rf` keeps re-runs from nesting a second copy inside `/tmp/ci/gateway`; the `gh api` downloads are subject to GitHub rate limiting, so a repeated run can return HTTP 429 — wait a minute or reuse the files already under `/tmp/ci/tests`.

The GitHub Actions workflow checks out Hermes, installs its dev + messaging dependencies, runs an upstream QQ adapter import smoke test, verifies this directory plugin with `hermes plugins doctor`, overlays `adapter.py` onto Hermes' `gateway/platforms/qqbot/adapter.py`, then runs the upstream QQ-related tests:

```text
tests/gateway/test_qqbot.py
tests/gateway/test_qqbot_credential_isolation.py
tests/gateway/test_qqbot_scope_paths.py
```

Finally, it runs this plugin's own regression tests.

## Notes

Default tests are mock-only. They do not connect to QQ, do not use real credentials, and do not send real messages.
