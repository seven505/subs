import asyncio
import httpx
import yaml
import os
import time
from pathlib import Path
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()

# ----------------------------------------
# ✅ 加载配置
def load_config():
    default = {
        "concurrent": 100,
        "timeout": 5,
        "global_timeout": 20,
        "max_delay": 1000,
        "min_speed_kbps": 300,
        "download_size_kb": 1024,
        "test_gpt": True,
        "test_youtube": True,
        "test_netflix": True,
        "test_disney": True,
        "test_tiktok": True,
        "rename_format": "{emoji}{country}_{id} |{speed}|{loss}|{yt}|{nf}|{d+}|{gpt}|{tk}",
        "sort_by": "speed",
    }
    config_file = Path("config.yaml")
    if not config_file.exists():
        console.print("[bold red]未找到 config.yaml，使用默认配置[/bold red]")
        return default
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            user_config = yaml.safe_load(f)
        default.update(user_config)
        console.print("[green]✔ 加载配置成功[/green]")
        return default
    except Exception as e:
        console.print(f"[red]配置读取失败：{e}，使用默认配置[/red]")
        return default

# ----------------------------------------
# ✅ 订阅地址（临时写死，也可放 config.yaml）
SOURCE_URLS = [
    "https://raw.githubusercontent.com/NiceVPN123/NiceVPN/main/utils/pool/output.yaml",
    "https://raw.githubusercontent.com/gfpcom/free-proxy-list/main/list/trojan.txt",
    "https://raw.githubusercontent.com/SamanGho/v2ray_collector/main/v2tel_links2.txt",
    "https://raw.githubusercontent.com/go4sharing/sub/main/sub.yaml",
    "https://raw.githubusercontent.com/anaer/Sub/refs/heads/main/proxies.yaml"
]

ALLOWED_TYPES = ["vmess", "vless", "ss", "trojan", "hysteria2", "tuic"]
OUTPUT_PATH = "output/all.yaml"
os.makedirs("output", exist_ok=True)

# ----------------------------------------
# ✅ 拉取所有订阅
async def fetch_all_subs():
    proxies = []
    async with httpx.AsyncClient(timeout=15) as client:
        for url in SOURCE_URLS:
            try:
                console.print(f"[blue]拉取订阅：{url}[/blue]")
                r = await client.get(url)
                data = yaml.safe_load(r.text)
                if "proxies" in data:
                    proxies.extend(data["proxies"])
                    console.print(f"[green]✔ 成功加载 {len(data['proxies'])} 条节点[/green]")
                else:
                    console.print(f"[yellow]⚠ 无 proxies 字段：{url}[/yellow]")
            except Exception as e:
                console.print(f"[red]❌ 拉取失败：{url} ➜ {e}[/red]")
    return proxies

# ----------------------------------------
# ✅ 检查节点结构
def is_valid_node(node):
    required = ["name", "server", "port", "type"]
    return all(k in node and node[k] for k in required) and node["type"] in ALLOWED_TYPES

# ----------------------------------------
# ✅ 测速函数
async def test_node_speed(node, config, semaphore):
    server = node["server"]
    port = int(node["port"])
    delay = None
    speed_kbps = 0

    test_url = "http://speedtest-sgp1.digitalocean.com/1mb.test"  # 可换成国内CDN地址

    try:
        start_time = time.perf_counter()
        async with semaphore:
            async with httpx.AsyncClient(timeout=config["timeout"]) as client:
                resp = await client.get(test_url)
                elapsed = time.perf_counter() - start_time
                size_kb = len(resp.content) / 1024
                speed_kbps = size_kb / elapsed
                delay = int(elapsed * 1000)
        return {
            "node": node,
            "delay": delay,
            "speed_kbps": speed_kbps,
        }
    except:
        return {
            "node": node,
            "delay": None,
            "speed_kbps": 0,
        }

# ----------------------------------------
# ✅ 国家 Emoji 检测
def detect_country_emoji(name):
    flags = {
        "香港": "🇭🇰", "HK": "🇭🇰", "日本": "🇯🇵", "JP": "🇯🇵", "台湾": "🇹🇼",
        "US": "🇺🇸", "美国": "🇺🇸", "SG": "🇸🇬", "新加坡": "🇸🇬", "DE": "🇩🇪",
    }
    for k, emoji in flags.items():
        if k.lower() in name.lower():
            return emoji, k
    return "🏳️", "UNK"

# ----------------------------------------
# ✅ 自动命名函数
def rename_node(node, result, config, idx):
    emoji, country = detect_country_emoji(node["name"])
    speed = f"{result['speed_kbps']/1024:.1f}MB/s" if result['speed_kbps'] > 0 else "0MB/s"
    delay = f"{result['delay']}ms" if result['delay'] else "timeout"

    yt = "YT" if True else "-"
    nf = "NF" if False else "-"
    dplus = "D+" if False else "-"
    gpt = "GPT" if False else "-"
    tk = "TK" if False else "-"

    new_name = config["rename_format"].format(
        emoji=emoji,
        country=country,
        id=str(idx).zfill(3),
        speed=speed,
        loss=delay,
        yt=yt,
        nf=nf,
        dplus=dplus,
        gpt=gpt,
        tk=tk
    )
    node["name"] = new_name
    return node

# ----------------------------------------
# ✅ 主执行流程
async def main():
    config = load_config()
    all_nodes = await fetch_all_subs()
    valid_nodes = [n for n in all_nodes if is_valid_node(n)]

    console.print(f"[cyan]共 {len(valid_nodes)} 个结构合格节点，开始测速...[/cyan]")

    semaphore = asyncio.Semaphore(config["concurrent"])
    speed_tasks = [test_node_speed(n, config, semaphore) for n in valid_nodes]
    results = await asyncio.gather(*speed_tasks)

    filtered = []
    for idx, res in enumerate(results):
        if res["delay"] and res["delay"] <= config["max_delay"] and res["speed_kbps"] >= config["min_speed_kbps"]:
            renamed = rename_node(res["node"], res, config, idx + 1)
            filtered.append(renamed)

    # 排序
    sort_key = "speed_kbps" if config["sort_by"] == "speed" else "delay"
    filtered.sort(key=lambda x: x.get(sort_key, 999999), reverse=True)

    # 输出 YAML 文件
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        yaml.dump({"proxies": filtered}, f, allow_unicode=True)

    console.print(f"[green]✅ 输出 {len(filtered)} 条合格节点至：{OUTPUT_PATH}[/green]")

if __name__ == "__main__":
    asyncio.run(main())
