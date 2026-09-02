# -*- coding: utf-8 -*-
# 钉钉 / 企业微信 / 飞书推送（晨会内嵌）
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.request
from typing import Optional

log = logging.getLogger("pusher")


def push_dingtalk(title: str, content: str,
                  webhook: Optional[str] = None) -> bool:
    """钉钉自定义机器人 markdown 推送"""
    webhook = webhook or os.environ.get("DINGTALK_WEBHOOK", "")
    if not webhook:
        log.warning("[PUSH] DINGTALK_WEBHOOK 未配置, 跳过钉钉推送")
        return False
    payload = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": content},
    }
    try:
        req = urllib.request.Request(
            webhook, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            ret = json.loads(r.read())
            ok = ret.get("errcode") == 0
            if ok:
                log.info(f"[PUSH] 钉钉推送成功: {title}")
            else:
                log.error(f"[PUSH] 钉钉推送失败: {ret}")
            return ok
    except Exception as e:
        log.error(f"[PUSH] 钉钉推送异常: {e}")
        return False


def push_wecom(title: str, content: str,
               webhook: Optional[str] = None) -> bool:
    """企业微信群机器人 markdown 推送"""
    webhook = webhook or os.environ.get("WECOM_WEBHOOK", "")
    if not webhook:
        log.warning("[PUSH] WECOM_WEBHOOK 未配置, 跳过企业微信推送")
        return False
    payload = {
        "msgtype": "markdown",
        "markdown": {"content": f"# {title}\n\n{content}"},
    }
    try:
        req = urllib.request.Request(
            webhook, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            ret = json.loads(r.read())
            ok = ret.get("errcode") == 0
            if ok:
                log.info(f"[PUSH] 企业微信推送成功: {title}")
            else:
                log.error(f"[PUSH] 企业微信推送失败: {ret}")
            return ok
    except Exception as e:
        log.error(f"[PUSH] 企业微信推送异常: {e}")
        return False


def push_console(title: str, content: str) -> bool:
    """控制台打印 -- 总是可用, 没配 webhook 时的兜底"""
    print()
    print("=" * 70)
    print(f"  [推送] {title}")
    print("=" * 70)
    print(content)
    print("=" * 70)
    return True


def _feishu_sign(secret: str, timestamp: int) -> str:
    """飞书机器人加签：HMAC-SHA256(timestamp + \\n + secret)，结果 base64"""
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    return base64.b64encode(hmac_code).decode("utf-8")


def push_feishu(title: str, content: str,
                webhook: Optional[str] = None,
                secret: Optional[str] = None) -> bool:
    """
    飞书自定义机器人 text 消息推送

    配置：
        FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/xxxxx
        FEISHU_SECRET=xxxxx   # 若机器人启用了签名校验则必填；未启用可留空
    """
    webhook = webhook or os.environ.get("FEISHU_WEBHOOK", "")
    if not webhook:
        log.warning("[PUSH] FEISHU_WEBHOOK 未配置, 跳过飞书推送")
        return False

    secret = secret or os.environ.get("FEISHU_SECRET", "")
    timestamp = int(time.time())

    payload: dict = {
        "msg_type": "text",
        "content": {
            "text": f"{title}\n\n{content}",
        },
    }
    if secret:
        payload["timestamp"] = str(timestamp)
        payload["sign"] = _feishu_sign(secret, timestamp)

    try:
        req = urllib.request.Request(
            webhook,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            ret = json.loads(r.read())
            ok = ret.get("code") == 0
            if ok:
                log.info(f"[PUSH] 飞书推送成功: {title}")
            else:
                log.error(f"[PUSH] 飞书推送失败: {ret}")
            return ok
    except Exception as e:
        log.error(f"[PUSH] 飞书推送异常: {e}")
        return False


def push_all(title: str, content: str) -> dict:
    """同时尝试所有渠道"""
    return {
        "console":  push_console(title, content),
        "dingtalk": push_dingtalk(title, content),
        "wecom":    push_wecom(title, content),
        "feishu":   push_feishu(title, content),
    }
