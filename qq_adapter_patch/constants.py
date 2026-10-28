"""QQBot package-level constants shared across adapter, onboard, and other modules."""

from __future__ import annotations

import os

QQBOT_VERSION = "1.1.0"  # bump on functional changes to the adapter package
# Portal domain is overridable (QQ_PORTAL_HOST) for corporate proxies / test environments.
PORTAL_HOST = os.getenv("QQ_PORTAL_HOST", "q.qq.com")

API_BASE = "https://api.sgroup.qq.com"
TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
GATEWAY_URL_PATH = "/gateway"
ONBOARD_CREATE_PATH = "/lite/create_bind_task"
ONBOARD_POLL_PATH = "/lite/poll_bind_result"
QR_URL_TEMPLATE = "https://q.qq.com/qqbot/openclaw/connect.html?task_id={task_id}&_wv=2&source=hermes"

DEFAULT_API_TIMEOUT = 30.0
FILE_UPLOAD_TIMEOUT = 120.0
CONNECT_TIMEOUT_SECONDS = 20.0
RECONNECT_BACKOFF = [2, 5, 10, 30, 60]
MAX_RECONNECT_ATTEMPTS = 100
RATE_LIMIT_DELAY = 60  # seconds
QUICK_DISCONNECT_THRESHOLD = 5.0  # seconds
MAX_QUICK_DISCONNECT_COUNT = 3
ONBOARD_POLL_INTERVAL = 2.0  # seconds between poll_bind_result calls
ONBOARD_API_TIMEOUT = 10.0

MAX_MESSAGE_LENGTH = 4000
DEDUP_WINDOW_SECONDS = 300
DEDUP_MAX_SIZE = 1000

# QQ Bot message types / file media types
MSG_TYPE_TEXT = 0
MSG_TYPE_MARKDOWN = 2
MSG_TYPE_MEDIA = 7
MSG_TYPE_INPUT_NOTIFY = 6
MEDIA_TYPE_IMAGE = 1
MEDIA_TYPE_VIDEO = 2
MEDIA_TYPE_VOICE = 3
MEDIA_TYPE_FILE = 4

# ── Fork: outbound failure classification (was inline in adapter.py) ──────────
#
# QQ classifies an outbound message as PASSIVE only when it carries ``msg_id``
# (a reply) or ``event_id``; without them it is an ACTIVE message. Passive
# anchors die — 5 minutes in groups/频道, 60 minutes in C2C — and each message
# accepts a limited number of passive replies, so once an anchor is dead no
# retry with it can ever succeed: drop it and resend as an active message.
# Codes come from the official tables (send-message pages + api-call-guide):
# https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/overview.html
REPLY_ANCHOR_DEAD_CODES = frozenset({
    304026,    # MSG_ID 回复的消息 id 错误
    304027,    # MSG_EXPIRE 回复的消息过期
    304103,    # 消息ID已过期，不能回复
    40034005,  # 回复消息msg_id已过期
    40034024,  # 请求参数msg_id无效或越权
    40034025,  # 请求参数event_id无效
    40034026,  # 请求参数event_id已过期
    40034128,  # 被动回复时间或次数超限
})

# Text fallbacks for responses that omit ``err_code``. Compared lowercased.
REPLY_ANCHOR_DEAD_MARKERS = (
    "msg_id已过期",
    "msgid已过期",
    "msg_id expired",
    "msgid expired",
    "消息id已过期",
    "被动回复时间或次数超限",
    "msg_id无效",
    "msg_id 无效",
)

# QQ returns this when the chat id does not exist on the endpoint we chose — in
# practice a group openid sent to /v2/users (or the reverse), which happens when
# the chat kind was guessed instead of known (fresh process after a gateway
# restart, ledger redelivery of a queued message). The cure is to flip the
# endpoint once, not to retry the same one.
ENDPOINT_WRONG_CODES = frozenset({
    40011028,  # 请求的资源不存在(用户/群已注销)
})

ENDPOINT_WRONG_MARKERS = (
    "资源不存在",
    "用户/群已注销",
)

# Upload failures worth another attempt: transport trouble and QQ's own
# "server hiccup, try again later" codes. A business rejection (bad bytes, no
# permission, wrong id, content too long) fails the same way on a retry, so it
# is raised at once instead of burning the retry budget. The previous substring
# test on "400" swept every 4xx code — and the 5xx-family codes QQ returns
# inside a 400 response — into the no-retry bucket.
UPLOAD_RETRYABLE_CODES = frozenset({
    40034004,  # 富媒体信息转存失败 (请重试)
    50055001,  # 消息发送异常，请稍后重试
    50055006,  # ARK消息发送异常，请稍后重试
})
