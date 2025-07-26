import yaml
import httpx
import asyncio
import base64
import re
import os
from pathlib import Path
from datetime import datetime

# ==== 配置参数 ====
CONFIG = {
    "subscribe_urls": [
        "https://raw.githubusercontent.com/NiceVPN123/NiceVPN/main/utils/pool/output.yaml",
        # 可添加更多订阅链接
    ],
    "max_delay": 1000,           # 最大延迟（毫秒）
    "min_speed": 1,              # 最低速度（MB/s）占位，目前未启用
    "timeout": 10,               # 单个测速超时时间（秒）
    "speed_test_url": "https://github.com/AaronFeng753/Waifu2x-Extension-GUI/releases/download/v2.21.12/Waifu2x-Extension-GUI-v2.21.12-Portable.7z",
    "output_file": "output/all.yaml",
    "log_file": "logs/subscription_summary.log"
}

# ==== 工具函数 ====

def b64_decode(data: str) -> str:
    try:
        data += '=' * (-len(data) % 4)  # 修正 padding
        return base64.urlsafe_b64decode(data).decode()
    except Exception:
        return ""

def load_yaml_from_url(url: str) -> list:
    try:
        r = httpx.get(url, timeout=15)
        if url.endswith(".txt"):
            # 多条 base64 链接组合，逐个解码
            links = [line.strip() for line in r.text.strip().splitlines() if line.strip()]
            nodes = []
            for link in links:
                if "://" in link:
                    proto = link.split("://")[0].lower()
                    if proto in ["vmess", "ss", "trojan", "vless"]:
                        nodes.append(parse_node(link))
            return nodes
        else:
            raw = yaml.safe_load(r.text)
            return raw.get("proxies", []) if isinstance(raw, dict) else []
    except Exception as e:
        print(f"订阅拉取失败: {url} | {e}")
        return []

def parse_node(link: str) -> dict:
    try:
        if link.startswith("vmess://"):
            decoded = b64_decode(link[8:])
            return {"name": "vmess", **yaml.safe_load(decoded)}
        elif link.startswith("ss://") or link.startswith("trojan://") or link.startswith("vless://"):
            return {"name": link[:link.find("://")], "server": link}
        else:
            return {}
    except Exception:
        return {}

# ==== 延迟测速核心 ====

async def test_delay(proxy_node: dict) -> int:
    try:
        proxy_url = to_httpx_proxy(proxy_node)
        async with httpx.AsyncClient(proxies=proxy_url, timeout=CONFIG["timeout"]) as client:
            start = asyncio.get_event_loop().time()
            await client.get(CONFIG["speed_test_url"])
            end = asyncio.get_event_loop().time()
            delay = int((end - start) * 1000)
            return delay
    except Exception as e:
        print(f"测速失败: {e}")
        return None

def to_httpx_proxy(node: dict) -> str:
    if node.get("type") == "ss":
        return f"http://{node['server']}:{node['port']}"
    elif node.get("type") == "vmess":
        return f"http://{node['server']}:{node['port']}"
    elif node.get("type") == "trojan":
        return f"http://{node['server']}:{node['port']}"
    return ""

# ==== 主执行流程 ====

async def main():
    all_nodes = []
    for url in CONFIG["subscribe_urls"]:
        nodes = load_yaml_from_url(url)
        print(f"✅ 成功解析 {len(nodes)} 条节点：{url}")
        all_nodes.extend(nodes)

    print(f"拉取到节点总数: {len(all_nodes)}")

    # 结构检查（保留 type 和 server 字段存在的）
    valid_nodes = [n for n in all_nodes if isinstance(n, dict) and "type" in n and "server" in n]
    print(f"结构合格节点数: {len(valid_nodes)}")

    # 并发测速
    results = await asyncio.gather(*[test_delay(n) for n in valid_nodes])
    qualified = []

    for node, delay in zip(valid_nodes, results):
        if delay is not None and delay < CONFIG["max_delay"]:
            node["name"] = rename_node(node, delay)
            qualified.append(node)

    print(f"最终输出节点数: {len(qualified)}")

    Path(CONFIG["output_file"]).parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG["output_file"], "w", encoding="utf-8") as f:
        yaml.dump({"proxies": qualified}, f, allow_unicode=True)

    log_summary(len(all_nodes), len(qualified))
    print(f"✅ 输出至 {CONFIG['output_file']} 完成")

# ==== 命名逻辑 ====

def rename_node(node: dict, delay: int) -> str:
    country = "🏳️UNK"
    if "name" in node and isinstance(node["name"], str):
        if "香港" in node["name"] or "HK" in node["name"]:
            country = "🇭🇰HK"
        elif "台湾" in node["name"] or "TW" in node["name"]:
            country = "🇨🇳TW"
        elif "日本" in node["name"] or "JP" in node["name"]:
            country = "🇯🇵JP"
        elif "新加坡" in node["name"] or "SG" in node["name"]:
            country = "🇸🇬SG"
        elif "美国" in node["name"] or "US" in node["name"]:
            country = "🇺🇸US"
        elif "韩国" in node["name"] or "KR" in node["name"]:
            country = "🇰🇷KR"
    name = f"{country}_{str(delay).zfill(3)}ms"
    return name

# ==== 日志输出 ====

def log_summary(total, success):
    Path(CONFIG["log_file"]).parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG["log_file"], "a", encoding="utf-8") as f:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        percent = round(success / total * 100, 2) if total > 0 else 0
        f.write(f"[{now}] 总节点数={total} 成功节点数={success} 成功占比={percent}%\n")

# ==== 启动 ====
if __name__ == "__main__":
    asyncio.run(main())