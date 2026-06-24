#!/usr/bin/env python3
import os
import sys
import requests
import datetime
import logging
from typing import Dict, Any, List

# ---------- 从环境变量读取配置 ----------
API_BASE = "https://api005.dnshe.com/index.php"
API_KEY = os.environ.get("DNSHE_API_KEY")
API_SECRET = os.environ.get("DNSHE_API_SECRET")
WECHAT_WEBHOOK = os.environ.get("WECHAT_WEBHOOK_URL", "")
RENEW_THRESHOLD_DAYS = int(os.environ.get("RENEW_THRESHOLD_DAYS", 180))

if not API_KEY or not API_SECRET:
    print("错误: 缺少 DNSHE_API_KEY 或 DNSHE_API_SECRET 环境变量", file=sys.stderr)
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ---------- API 封装 ----------
def list_subdomains(page: int = 1, per_page: int = 200) -> Dict[str, Any]:
    url = f"{API_BASE}?m=domain_hub&endpoint=subdomains&action=list"
    params = {"page": page, "per_page": per_page, "sort_by": "id", "sort_dir": "desc"}
    headers = {"X-API-Key": API_KEY, "X-API-Secret": API_SECRET}
    resp = requests.get(url, params=params, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise Exception(f"List API error: {data}")
    return data

def fetch_all_subdomains() -> List[Dict[str, Any]]:
    all_subdomains = []
    page = 1
    while True:
        data = list_subdomains(page=page)
        subdomains = data.get("subdomains", [])
        if not subdomains:
            break
        all_subdomains.extend(subdomains)
        if not data.get("pagination", {}).get("has_more", False):
            break
        page += 1
    return all_subdomains

def renew_subdomain(subdomain_id: int) -> Dict[str, Any]:
    url = f"{API_BASE}?m=domain_hub&endpoint=subdomains&action=renew"
    headers = {"X-API-Key": API_KEY, "X-API-Secret": API_SECRET}
    payload = {"subdomain_id": subdomain_id}
    resp = requests.post(url, headers=headers, json=payload, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise Exception(f"Renew API error: {data}")
    return data

def send_wechat(text: str) -> None:
    if not WECHAT_WEBHOOK or "YOUR_KEY" in WECHAT_WEBHOOK:
        logger.warning("微信 Webhook 未配置，跳过推送")
        return
    payload = {"msgtype": "text", "text": {"content": text}}
    try:
        resp = requests.post(WECHAT_WEBHOOK, json=payload, timeout=5)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"发送微信失败: {e}")

def days_until_expiry(expires_at: str) -> int:
    exp = datetime.datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
    delta = exp - datetime.datetime.now()
    return max(0, delta.days)

# ---------- 主逻辑 ----------
def main():
    try:
        logger.info("开始获取所有子域名...")
        subdomains = fetch_all_subdomains()
        if not subdomains:
            send_wechat("⚠️ 当前没有子域名记录")
            return

        domain_status_list = []   # 存储所有域名的状态信息（用于总览）
        renew_actions = []        # 存储续期操作结果（仅当触发续期）

        for sub in subdomains:
            sid = sub["id"]
            full_domain = sub["full_domain"]
            expires_at = sub["expires_at"]
            status = sub["status"]
            never_expires = sub.get("never_expires", 0)

            if never_expires == 1:
                # 永不过期的域名单独标记，不计算剩余天数
                domain_status_list.append(f"🔒 {full_domain} | 永不过期 | {status}")
                logger.info(f"{full_domain} 永不过期，跳过")
                continue

            remain = days_until_expiry(expires_at)
            domain_status_list.append(f"📌 {full_domain} | 剩余 {remain} 天 | 过期 {expires_at} | 状态 {status}")
            logger.info(f"{full_domain} 剩余 {remain} 天，状态 {status}")

            # 判断是否应续期：Registered 且剩余天数 <= 阈值
            if remain <= RENEW_THRESHOLD_DAYS and status == "Registered":
                try:
                    r = renew_subdomain(sid)
                    new_exp = r["new_expires_at"]
                    charged = r.get("charged_amount", 0)
                    action_msg = (f"✅ {full_domain} 续期成功，新过期 {new_exp}，扣费 {charged} 元")
                    renew_actions.append(action_msg)
                    logger.info(f"续期成功: {full_domain} -> {new_exp}")
                except Exception as e:
                    action_msg = f"❌ {full_domain} 续期失败，错误: {str(e)}"
                    renew_actions.append(action_msg)
                    logger.error(action_msg)

        # 构建微信消息内容
        lines = []
        lines.append("【所有域名剩余时间】")
        lines.extend(domain_status_list if domain_status_list else ["（无有效域名）"])
        lines.append("")
        lines.append("【续期操作结果】")
        if renew_actions:
            lines.extend(renew_actions)
        else:
            lines.append("无域名触发续期（所有域名剩余天数均 > 阈值或状态异常）")

        summary = "\n".join(lines)
        send_wechat(summary)

    except Exception as e:
        err_text = f"❌ 脚本运行异常: {str(e)}"
        logger.error(err_text)
        send_wechat(err_text)
        sys.exit(1)

if __name__ == "__main__":
    main()
