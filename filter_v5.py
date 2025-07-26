import yaml
import httpx
import asyncio
import base64
import re
import os
import socket
from pathlib import Path
from datetime import datetime

# === 加载配置 ===
with open("config.yaml", "r", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

# === 工具函数 ===

def b64_decode(data: str) -> str:
    try:
        data += '=' * (-len(data) % 4)
        return base64.urlsafe_b64decode(data.encode()).decode()
    except Exception:
        return ""

def load_yaml_from_url(url: str) -> list:
    try:
        r = httpx.get(url, timeout=15)
        if url.endswith(".txt"):
            links = [line.strip() for line in r.text.strip().splitlines() if line.strip()]
            return [parse_node(link) for link in links if "://" in link]
        else:
            raw = yaml.safe_load(r.text)
            return raw.get("proxies", []) if isinstance(raw, dict) else []
    except Exception as e:
        print(f"❌ 订阅拉取失败: {url} | {e}")
        return []

def parse_node(link: str) -> dict:
    try:
        if link.startswith("vmess://"):
            decoded = b64_decode(link[8:])
            return {"type": "vmess", **yaml.safe_load(decoded)}
        elif link.startswith("ss://"):
            return {"type": "ss", "server": extract_ss_server(link), "port": 443}
        elif link.startswith("trojan://"):
            m = re.match(r"trojan://[^@]+@(?P<server>[^:]+):(?P<port>\d+)", link)
            if m:
                return {"type": "trojan", "server": m["server"], "port": int(m["port"])}
    except Exception:
        return {}
    return {}

def extract_ss_server(link):
    try:
        link = link.split('#')[0].replace("ss://", "")
        decoded = b64_decode(link)
        if "@" in decoded:
            return decoded.split("@")[-1].split(":")[0]
        return decoded.split(":")[0]
    except:
        return "unknown"

# === Socket 延迟测试 ===

async def test_socket(server: str, port: int, timeout: int = 3):
    try:
        loop = asyncio.get_event_loop()
        start = loop.time()
        await asyncio.wait_for(loop.getaddrinfo(server, port), timeout)
        reader, writer = await asyncio.wait_for(asyncio.open_connection(server, port), timeout)
        end = loop.time()
        writer.close()
        await writer.wait_closed()
        return int((end - start) * 1000)
    except:
        return None

# === 主程序 ===

async def main():
    all_nodes = []
    for url in CONFIG["subscribe_urls"]:
        nodes = load_yaml_from_url(url)
        print(f"✅ 成功解析 {len(nodes)} 条节点：{url}")
        all_nodes.extend(nodes)

    print(f"📦 拉取到节点总数: {len(all_nodes)}")
    valid_nodes = [n for n in all_nodes if isinstance(n, dict) and "server" in n and "type" in n]
    print(f"🔍 结构合格节点数: {len(valid_nodes)}")

    results = await asyncio.gather(*[
        test_socket(n["server"], int(n.get("port", 443)), CONFIG.get("timeout", 3))
        for n in valid_nodes
    ])

    filtered = []
    for node, delay in zip(valid_nodes, results):
        if delay is not None and delay <= CONFIG.get("max_delay", 1000):
            node["name"] = rename_node(node, delay)
            filtered.append(node)

    print(f"✅ 最终输出节点数: {len(filtered)}")

    Path(CONFIG["output_file"]).parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG["output_file"], "w", encoding="utf-8") as f:
        yaml.dump({"proxies": filtered}, f, allow_unicode=True)

    log_summary(len(all_nodes), len(filtered))
    print(f"📁 输出至 {CONFIG['output_file']} 完成")

# === 节点命名 ===

def rename_node(node: dict, delay: int) -> str:
    name = node.get("name", "")
    country = "🏳️UNK"
    for tag, code in [("香港", "🇭🇰HK"), ("台湾", "🇨🇳TW"), ("日本", "🇯🇵JP"),
                      ("新加坡", "🇸🇬SG"), ("美国", "🇺🇸US"), ("韩国", "🇰🇷KR")]:
        if tag in name or code in name:
            country = code
    return f"{country}_{str(delay).zfill(3)}ms"

# === 日志 ===

def log_summary(total, success):
    Path(CONFIG["log_file"]).parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG["log_file"], "a", encoding="utf-8") as f:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        percent = round(success / total * 100, 2) if total > 0 else 0
        f.write(f"[{now}] 总节点数={total} 成功节点数={success} 成功占比={percent}%\n")

# === 启动 ===

if __name__ == "__main__":
    asyncio.run(main())