# Hermes QQ 适配器补丁

Hermes 目录插件，官方 QQ 机器人插件的完整源码 fork。

插件注册平台 `qqbot`，在运行时替换 Hermes 内置的 QQ 适配器，携带针对 QQ 群/私聊投递行为的本地修复。上游已把 QQ 适配器做成完整独立插件（`plugins/platforms/qqbot/`），所以这里直接 fork 整包源码，而不是只覆盖单个 `adapter.py`。

## 改了什么

对用户可见的行为变化：

- **长回复不再丢。** QQ 只允许机器人在限定时间内“回复”某条消息（群聊 5 分钟、私聊 60 分钟），且一条消息可被动回复的次数有限。超时后插件会把同一内容改成主动消息发出去，而不是拿着一个永远不可能成功的引用重试、最后把回复丢掉。文本、审批/确认按钮、图片/语音/视频/文件都是如此。
- **网关重启后，排队中的群聊回复仍能送达。** 重启后适配器手上的会话类型表是空的，会把会话默认当成私聊：私聊恰好猜对，群聊的 openid 则会被发到私聊接口，被 QQ 拒绝（`40011028 请求的资源不存在`）后丢掉。现在启动时会从网关的路由表补全会话类型，排队的群消息因此发往正确的接口。**QQ 频道（guild）的这条链路暂时不修（没人用）**：路由表把频道记成 group，无法据它还原频道类型，重启后补投的频道消息仍会发错端点。
- **群内支持成员白名单。** 除了放行整个群，还能限制只有哪些成员可以触发机器人。
- **被拒绝的消息会记日志**，含发送者、会话 openid、拒绝它的策略和原文，方便你把 openid 加进白名单。

## 目录结构

上游整包源码放在 `qq_adapter_patch/`，与本仓库根目录分开，根层只留一个 `__init__.py`：

```text
qq-adapter-patch/
  __init__.py            # 只转发 register，避免顶层模块遮蔽 Hermes 自己的模块
  qq_adapter_patch/      # 上游 plugins/platforms/qqbot/ 的全部源码
  plugin.yaml  README.md  pyproject.toml  tests/
```

补丁按上游的文件职责落位，`git diff` 即可看出补丁集：

- `adapter.py`：投递回退（被动回复锚点失效改发主动消息、端点猜错翻一次）、群 ACL（成员白名单与拒绝日志）、`QQBotAPIError`。
- `constants.py`：QQ 的错误码集合（被动回复失效、端点错误、上传可重试）。
- `chunked_upload.py`：上传失败是否值得重试的分类。
- `gateway_env.py`：成员白名单的 env 声明，与上游的 `QQ_GROUP_ALLOWED_USERS` 并列。

其余文件与上游一致。

这不是独立的 Python 程序，依赖 Hermes 的运行时模块（如 `gateway.*`）。

适配的 Hermes 源码布局中，QQ 插件位于：

```text
plugins/platforms/qqbot/
```

## 上游基线

`qq_adapter_patch/` 取自上游 **v0.22.5**（commit `bf0203a7`），在其之上叠加本仓库的补丁。CI 的上游测试步骤钉的是**上游最新 release tag**。

以后跟随新版本时：把新 tag 的 `plugins/platforms/qqbot/` 整包覆盖到 `qq_adapter_patch/`，重新打上 `adapter.py` 的补丁。导入原包与打补丁分成两次提交，方便单独查看补丁。

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
QQ_GROUP_ALLOWED_USERS=group_openid_1,group_openid_2
QQ_GROUP_MEMBER_ALLOW_FROM=member_openid_1,member_openid_2
```

说明：

- `QQ_GROUP_ALLOWED_USERS` 是上游声明的群白名单 env，由 `gateway_env.py` 桥接进 `extra["group_allow_from"]`；`QQ_GROUP_MEMBER_ALLOW_FROM` 是本插件新增的成员白名单 env，同样声明在 `gateway_env.py`。
- 旧的自定义名 `QQ_GROUP_ALLOW_FROM` 仍然兼容，但请迁移到 `QQ_GROUP_ALLOWED_USERS`。
- `group_policy` 与 `dm_policy` 没有 env 写法，请在 `config.yaml` 里设置。
- 两个白名单都支持 `*` 通配。
- 被拒绝的消息以 INFO 级别记录 group/member openid、原因（`group_not_in_allowlist` / `member_not_in_allowlist` 等）、策略和原文，可据此发现需要加白名单的 openid。

## 测试

插件自身的测试需要 pytest、pytest-asyncio，以及 Hermes gateway 包导入的运行时依赖。一个最小 venv 就够：

```bash
uv venv .venv --python 3.14
uv pip install --python .venv/bin/python pytest pytest-asyncio pyyaml ruamel.yaml aiohttp httpx websockets psutil python-dotenv
```

然后在本仓库根目录执行：

```bash
PYTHONPATH=/opt/hermes .venv/bin/pytest tests -q
```

用 `.venv/bin/pytest` 而不是 `.venv/bin/python -m pytest`：后者把当前目录放进 `sys.path`，本仓库根的模块会盖住 Hermes 的同名模块。

`/opt/hermes/.venv` 跑不了这些测试：它是 root 所有，且不带 pytest。

CI 对着**上游最新 release tag** 测试，tag 在运行时解析——那才是实际部署的代码树，而上游 `main` 变化太快（几小时前合入的测试会在对应修复移植过来之前就让 fork 挂掉）。解析到的 tag 会打进 CI 日志。想提前知道结果，可以在本地复现这一步。先在仓库根目录记下路径，下面用 `$REPO` 引用：

```bash
REPO=$PWD
TAG=$(gh release view -R NousResearch/hermes-agent --json tagName --jq .tagName)
rm -rf /tmp/ci && mkdir -p /tmp/ci/plugins/platforms
git clone --depth 1 --branch "$TAG" --filter=blob:none --sparse \
  https://github.com/NousResearch/hermes-agent.git /tmp/ci/hermes
git -C /tmp/ci/hermes sparse-checkout set tests
cp -a /opt/hermes/plugins/__init__.py /tmp/ci/plugins/
cp -a /opt/hermes/plugins/platforms/__init__.py /tmp/ci/plugins/platforms/
cp -a "$REPO/qq_adapter_patch" /tmp/ci/plugins/platforms/qqbot
cd /tmp/ci/hermes
HERMES_HOME=/var/tmp/hermes-ci-home PYTHONPATH=/tmp/ci:/opt/hermes \
  "$REPO/.venv/bin/python" -m pytest -q -o asyncio_mode=auto \
  tests/gateway/test_qqbot.py tests/gateway/test_qqbot_credential_isolation.py \
  tests/gateway/test_qqbot_scope_paths.py tests/gateway/test_qqbot_update_prompt_key.py
```

这是拿本机安装的 Hermes 运行时去跑该 tag 的测试，所以安装树与 tag 必须是同一个 release：`/opt/hermes/bin/hermes --version` 会打印出来（写这份文档时是 `v0.22.5 (2026.9.24) · upstream bf0203a7`）。

几个只在本地出现的坑：

- `/tmp/ci` 必须排在 `PYTHONPATH` 最前面，`plugins.platforms.qqbot.*` 才会解析到本仓库那份；否则上游测试跑的是安装树里的原版适配器。
- `HERMES_HOME` 要指到 `/opt/data` 之外，否则上游 `tests/home_io_guard.py` 会把影子目录判成真实 Hermes home，抛 `TEST BUG: file I/O against the REAL hermes home`。
- 缺 `python-dotenv` 时，`test_qqbot_scope_paths.py` 会整片失败（`ModuleNotFoundError: No module named 'dotenv'`），与补丁无关。

GitHub Actions 的流程是：检出 Hermes，安装它的 dev/test 依赖组与 messaging extra，跑一次上游 QQ 适配器的导入冒烟测试，用 `hermes plugins doctor` 校验本目录插件，把 `qq_adapter_patch/*.py` 覆盖到 Hermes 的 `plugins/platforms/qqbot/`（**保留上游的 `plugin.yaml`**：Hermes 靠 `__init__.py` + `plugin.yaml` 认定内置平台，缺了它 `bundled_authz("qqbot")` 会返回空，scope/authz 测试就会红），然后跑上面四个上游测试文件，最后跑本插件自己的回归测试。

## 说明

- **QQ 频道（guild）需要按频道放行。** 频道的收发链路本身是通的（回复走 `/channels/{channel_id}/messages`），但频道里 QQ 给的是 guild 成员雪花 id（如 19 位数字），与 QQ 群/私聊使用的 openid 不是同一套标识，匹配不上 `QQ_ALLOWED_USERS` 里的 openid，所以要在 `platforms.qqbot.extra.group_allowed_chats` 里放行频道 id。**频道私信**（guild DM）另说：上游没有对应的发送路径，放行也回不了消息，暂时不修。
- 默认测试全部是 mock：不连接 QQ、不使用真实凭据、不发送真实消息。
