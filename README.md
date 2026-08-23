# Hermes QQ Adapter Patch

Hermes directory plugin for the official QQ Bot adapter.

This plugin registers platform `qqbot` and replaces Hermes' built-in QQ adapter at runtime. It carries local fixes for QQ group/private delivery behavior.

## What is patched

- Group member allowlist via `QQ_GROUP_ALLOWED_MEMBERS` or `extra.group_member_allow_from`.
- Passive reply quota handling: when QQ reports `被动回复时间或者次数超过限制`, drop `msg_id` and retry once as an active message.
- Group-to-DM fallback when group send fails.
- P0 regression fix: a private C2C chat must not be polluted as a group chat by delivery ledger lookup.
- Metadata guard: group provenance is used only when `source_chat_id` matches the current target chat.

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

## Required configuration

Set QQ credentials in the active profile secret scope or environment:

```text
QQ_APP_ID
QQ_CLIENT_SECRET
```

Optional group-member restriction:

```text
QQ_GROUP_ALLOWED_MEMBERS=member_openid_1,member_openid_2
```

Or configure `extra.group_member_allow_from` in the QQ platform config.

## Tests

From this repo, with Hermes source available at `/opt/hermes`:

```bash
PYTHONPATH=/opt/hermes /opt/hermes/.venv/bin/python -m pytest -q tests
```

The GitHub Actions workflow checks out Hermes, installs its dev + messaging dependencies, runs an upstream QQ adapter import smoke test, then runs this plugin's tests.

## Notes

Default tests are mock-only. They do not connect to QQ, do not use real credentials, and do not send real messages.
