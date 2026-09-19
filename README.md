# Hermes QQ Adapter Patch

Hermes directory plugin for the official QQ Bot adapter.

This plugin registers platform `qqbot` and replaces Hermes' built-in QQ adapter at runtime. It carries local fixes for QQ group/private delivery behavior.

## What is patched

- ACL rejection logging at intake: rejected C2C / group / guild / guild-DM
  messages are logged at INFO with the sender and chat openids, active policy,
  reject reason and raw message content.
- Group ACL config: env fallback `QQ_GROUP_ALLOW_FROM` for
  `extra.group_allow_from`; new member-level filter for group messages via
  `extra.group_member_allow_from` (env `QQ_GROUP_MEMBER_ALLOW_FROM`), enforced
  after the group gate; unset list = any member.
- Passive reply anchor fallback: when QQ rejects an outbound message because
  its `msg_id` / `event_id` anchor is no longer usable (expired — 5 min in
  group/channel, 60 min in C2C — or the passive reply quota for that message is
  used up), the adapter drops the anchor and resends the same content once as
  an ACTIVE message instead of retrying the dead anchor and silently dropping
  the reply. Covers text (C2C / group / guild), keyboard messages (approval and
  update prompts, keyboard kept — they bypass the text path entirely) and media
  (the uploaded `file_info` is reused, never re-uploaded). The fallback fires at
  most once per send, and a dead-anchor terminal failure is returned
  non-retryable so the gateway does not replay the dead anchor.
- Error-code plumbing the fallback needs: `_api_request` raises
  `QQBotAPIError(RuntimeError)` carrying `err_code` (the message text keeps its
  old wording plus a trailing `(err_code=...)`). Anchor-death is classified by
  code — 304026, 304027, 304103, 40034005, 40034024, 40034025, 40034026,
  40034128 — with a message-text fallback for responses that omit the code.
- Approval authz namespace sync: `_parse_gateway_session_key` accepts any
  non-empty profile namespace (`agent:<profile>:qqbot:...`) instead of the
  literal `main`, and `_is_authorized_interaction_for_session` accepts
  `chat_type="dm"` alongside `"c2c"`. Without this, approval button clicks under
  a named profile were rejected as unauthorized and the approval timed out.

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

CI checks out Hermes `main` **unpinned**, so upstream drift breaks the upstream step before it breaks anything here. Reproduce that step locally instead of pushing to find out:

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
