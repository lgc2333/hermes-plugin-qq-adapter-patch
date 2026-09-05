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

From this repo, with Hermes source available at `/opt/hermes`:

```bash
PYTHONPATH=/opt/hermes /opt/hermes/.venv/bin/python -m pytest -q tests
```

The GitHub Actions workflow checks out Hermes, installs its dev + messaging dependencies, runs an upstream QQ adapter import smoke test, verifies this directory plugin with `hermes plugins doctor`, overlays `adapter.py` onto Hermes' `gateway/platforms/qqbot/adapter.py`, then runs the upstream QQ-related tests:

```text
tests/gateway/test_qqbot.py
tests/gateway/test_qqbot_credential_isolation.py
tests/gateway/test_qqbot_scope_paths.py
```

Finally, it runs this plugin's own regression tests.

## Notes

Default tests are mock-only. They do not connect to QQ, do not use real credentials, and do not send real messages.
