# Hermes QQ 适配器补丁

Hermes 目录插件，用于官方 QQ 机器人适配器。

插件注册平台 `qqbot`，在运行时替换 Hermes 内置的 QQ 适配器，携带针对 QQ 群/私聊投递行为的本地修复。

## 改了什么

对用户可见的行为变化：

- **长回复不再丢。** QQ 只允许机器人在限定时间内“回复”某条消息（群聊 5 分钟、私聊 60 分钟），且一条消息可被动回复的次数有限。超时后插件会把同一内容改成主动消息发出去，而不是拿着一个永远不可能成功的引用重试、最后把回复丢掉。文本、审批/确认按钮、图片/语音/视频/文件都是如此。
- **网关重启时排队中的回复仍会送达。** 启动时插件会从网关的路由表得知哪些会话是群、哪些是私聊，排队中的消息因此发往正确的会话，而不是发给一个不存在的会话后丢掉。
- **审批与确认按钮可用。** 点击即可完成审批；此前在命名 profile 下点击可能被判为未授权，或者干脆没发按钮、只收到纯文本的 `/approve` 提示。
- **群内支持成员白名单。** 除了放行整个群，还能限制只有哪些成员可以触发机器人。
- **被拒绝的消息会记日志**，含发送者、会话 openid、拒绝它的策略和原文，方便你把 openid 加进白名单。

## 兼容性

这不是独立的 Python 程序，依赖 Hermes 的运行时模块（如 `gateway.*`、`gateway.platforms.qqbot.*`）。

适配的 Hermes 源码布局中，QQ 适配器位于：

```text
gateway/platforms/qqbot/
```

## 上游基线

`adapter.py` 取自上游 **v2026.9.21**（commit `d337b736`，即本机安装的版本），在其之上叠加本仓库的补丁。以前由本仓库移植的部分现在上游已自带，故不再重复：profile 命名空间的审批鉴权、`_send_exec_approval_prompt` 钩子、可配置的 STT 超时、按 profile 作用域的 opt-in、异步媒体缓存、可配置的 `gateway.trust_env`。CI 的上游测试步骤钉的是**上游最新 release tag**。

以后跟随新版本时：把新的 `gateway/platforms/qqbot/adapter.py` 整份覆盖过来，再重新打上下面的补丁。该文件每次发布都可能被重构，所以 diff/merge 没有意义。导入原文件与打补丁分成两次提交，方便单独查看补丁。

## 安装

使用当前 profile 的 `HERMES_HOME`，不要写死 `~/.hermes`。

1. 复制目录插件：

```bash
mkdir -p "$HERMES_HOME/plugins"
cp -R qq-adapter-patch "$HERMES_HOME/plugins/qq-adapter-patch"
```

2. 启用：

```bash
hermes plugins enable qq-adapter-patch
```

3. 检查：

```bash
hermes plugins doctor "$HERMES_HOME/plugins/qq-adapter-patch"
hermes plugins list --enabled
```

4. 重启网关，或重启加载平台的那个 Hermes 进程。

## 额外配置

群 ACL 写在 QQ 平台配置里（`config.yaml` 的 `platforms.qqbot.extra`）：

```yaml
group_policy: "allowlist"
group_allow_from:
  - "group_openid_1"
group_member_allow_from:
  - "member_openid_1"
```

`group_policy` 取值 `open` / `allowlist` / `disabled` / `pairing`。`group_allow_from` 是 group_openid 白名单，在 `allowlist` 策略下留空表示全部拒绝。`group_member_allow_from` 是可选项，用于在已放行的群里再筛 member_openid，留空表示不限成员。

对应的环境变量（仅在缺少 `extra` 键时才读取）：

```text
QQ_GROUP_ALLOW_FROM=group_openid_1,group_openid_2
QQ_GROUP_MEMBER_ALLOW_FROM=member_openid_1,member_openid_2
```

说明：

- `QQ_GROUP_ALLOW_FROM` / `QQ_GROUP_MEMBER_ALLOW_FROM` 是本插件自定的 env 名，比核心桥接的 `QQ_GROUP_ALLOWED_USERS` 更直观；只在对应的 `extra` 键缺失时生效。
- `group_policy` 与 `dm_policy` 没有 env 写法，请在 `config.yaml` 里设置。
- 两个白名单都支持 `*` 通配。
- 被拒绝的消息以 INFO 级别记录 group/member openid、原因（`group_not_in_allowlist` / `member_not_in_allowlist` 等）、策略和原文，可据此发现需要加白名单的 openid。

## 测试

插件自身的测试需要 pytest、pytest-asyncio，以及 Hermes gateway 包导入的运行时依赖。一个最小 venv 就够：

```bash
uv venv .venv --python 3.13
uv pip install --python .venv/bin/python pytest pytest-asyncio pyyaml aiohttp httpx websockets psutil
```

然后在本仓库根目录执行：

```bash
PYTHONPATH=/opt/hermes:$PWD .venv/bin/python -m pytest tests -q
```

`/opt/hermes/.venv` 跑不了这些测试：它是 root 所有，且不带 pytest。

CI 对着**上游最新 release tag** 测试，tag 在运行时解析——那才是实际部署的代码树，而上游 `main` 变化太快（几小时前合入的测试会在对应修复移植过来之前就让 fork 挂掉）。解析到的 tag 会打进 CI 日志。想提前知道结果，可以在本地复现这一步。先在仓库根目录记下路径，下面用 `$REPO` 引用：

```bash
REPO=$PWD
TAG=$(gh release view -R NousResearch/hermes-agent --json tagName --jq .tagName)
mkdir -p /tmp/ci/tests/gateway && rm -rf /tmp/ci/gateway && cp -a /opt/hermes/gateway /tmp/ci/gateway
cp adapter.py /tmp/ci/gateway/platforms/qqbot/adapter.py
for f in test_qqbot.py test_qqbot_credential_isolation.py test_qqbot_scope_paths.py test_qqbot_update_prompt_key.py conftest.py; do
  gh api -H "Accept: application/vnd.github.raw" "repos/NousResearch/hermes-agent/contents/tests/gateway/$f?ref=$TAG" > "/tmp/ci/tests/gateway/$f"
done
gh api -H "Accept: application/vnd.github.raw" "repos/NousResearch/hermes-agent/contents/tests/conftest.py?ref=$TAG" > /tmp/ci/tests/conftest.py
cd /tmp/ci && PYTHONPATH=/tmp/ci:/opt/hermes "$REPO/.venv/bin/python" -m pytest tests/gateway/test_qqbot.py tests/gateway/test_qqbot_credential_isolation.py tests/gateway/test_qqbot_scope_paths.py tests/gateway/test_qqbot_update_prompt_key.py -q -o asyncio_mode=auto
```

这是拿本机安装的 `gateway/` 代码树去跑该 tag 的测试，所以两者必须是同一个 release：`/opt/hermes/bin/hermes --version` 会打印出来（写这份文档时是 `v0.21.4 (2026.9.21) · upstream d337b736`，即 `v2026.9.21`）。

覆盖顺序很关键：`/tmp/ci` 必须排在 `PYTHONPATH` 最前面，`gateway.platforms.qqbot.adapter` 才会解析到带本插件 `adapter.py` 的那份。`rm -rf` 是为了避免重复执行时在 `/tmp/ci/gateway` 里再嵌一层副本；`gh api` 的下载受 GitHub 限流影响，反复执行可能返回 HTTP 429——等一分钟，或直接复用 `/tmp/ci/tests` 下已有的文件。

GitHub Actions 的流程是：检出 Hermes，安装它的 dev + messaging 依赖，跑一次上游 QQ 适配器的导入冒烟测试，用 `hermes plugins doctor` 校验本目录插件，把 `adapter.py` 覆盖到 Hermes 的 `gateway/platforms/qqbot/adapter.py`，然后跑上游与 QQ 相关的测试：

```text
tests/gateway/test_qqbot.py
tests/gateway/test_qqbot_credential_isolation.py
tests/gateway/test_qqbot_scope_paths.py
tests/gateway/test_qqbot_update_prompt_key.py
```

最后再跑本插件自己的回归测试。

## 说明

默认测试全部是 mock：不连接 QQ、不使用真实凭据、不发送真实消息。
