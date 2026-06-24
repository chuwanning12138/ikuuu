#!/usr/bin/env python3
import os
import sys
import requests
import datetime
from typing import Dict, Any, List

# ---------- 从环境变量读取配置 ----------
API_BASE = "https://api005.dnshe.com/index.php"
API_KEY = os.environ.get("DNSHE_API_KEY")
API_SECRET = os.environ.get("DNSHE_API_SECRET")
WECHAT_WEBHOOK = os.environ.get("WECHAT_WEBHOOK_URL", "")
RENEW_THRESHOLD_DAYS = int(os.environ.get("RENEW_THRESHOLD_DAYS", 180))

if not API_KEY or not API_SECRET:
    # 错误仍输出到 stderr，便于排查
    print("错误: 缺少 DNSHE_API_KEY 或 DNSHE_API_SECRET 环境变量", file=sys.stderr)
    sys.exit(1)

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
        # 未配置时只在控制台打印警告（仍输出到 stderr）
        print("警告: 微信 Webhook 未配置，消息未发送", file=sys.stderr)
        return
    payload = {"msgtype": "text", "text": {"content": text}}
    try:
        requests.post(WECHAT_WEBHOOK, json=payload, timeout=5).raise_for_status()
    except Exception as e:
        # 微信发送失败时打印错误到 stderr
        print(f"微信发送失败: {e}", file=sys.stderr)

def days_until_expiry(expires_at: str) -> int:
    exp = datetime.datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
    delta = exp - datetime.datetime.now()
    return max(0, delta.days)

# ---------- 主逻辑 ----------
def main():
    try:
        subdomains = fetch_all_subdomains()
        if not subdomains:
            send_wechat("⚠️ 当前没有子域名记录")
            return

        domain_status_list = []
        renew_actions = []

        for sub in subdomains:
            sid = sub["id"]
            full_domain = sub["full_domain"]
            expires_at = sub["expires_at"]
            status = sub["status"]
            never_expires = sub.get("never_expires", 0)

            if never_expires == 1:
                domain_status_list.append(f"🔒 {full_domain} | 永不过期 | {status}")
                continue

            remain = days_until_expiry(expires_at)
            domain_status_list.append(f"📌 {full_domain} | 剩余 {remain} 天 | 过期 {expires_at} | 状态 {status}")

            if remain <= RENEW_THRESHOLD_DAYS and status == "Registered":
                try:
                    r = renew_subdomain(sid)
                    new_exp = r["new_expires_at"]
                    charged = r.get("charged_amount", 0)
                    renew_actions.append(f"✅ {full_domain} 续期成功，新过期 {new_exp}，扣费 {charged} 元")
                except Exception as e:
                    renew_actions.append(f"❌ {full_domain} 续期失败，错误: {str(e)}")

        # 构建微信消息
        lines = []
        lines.append("【所有域名剩余时间】")
        lines.extend(domain_status_list if domain_status_list else ["（无有效域名）"])
        lines.append("")
        lines.append("【续期操作结果】")
        if renew_actions:
            lines.extend(renew_actions)
        else:
            lines.append("无域名触发续期（所有域名剩余天数均 > 阈值或状态异常）")

        send_wechat("\n".join(lines))

    except Exception as e:
        # 全局异常仍输出到 stderr，方便调试
        print(f"脚本异常: {e}", file=sys.stderr)
        send_wechat(f"❌ 脚本运行异常: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
