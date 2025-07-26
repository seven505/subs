import asyncio
import base64
import yaml
import httpx
import time
import os
from pathlib import Path
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()

OUTPUT_PATH = "output/all.yaml"
LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)
os.makedirs("output", exist_ok=True)

# 加载配置
def load_config():
    with open("config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)

# 解析订阅，支持 yaml / base64 txt / json（可扩展）
def parse_sub_content(text):
    # 尝试yaml解析
    try:
        data = yaml.safe_load(text)
        if isinstance(data, dict) and "proxies" in data:
            return data["proxies"]
    except Exception:
        pass
    # 试base64解码，再解析yaml
    try:
        decoded = base64.b64decode(text).decode()
        data = yaml.safe_load(decoded)
        if isinstance(data, dict) and "proxies" in data:
            return data["proxies"]
    except Exception:
        pass
    console.print("[red]订阅内容解析失败，非标准yaml/base64格式[/red]")
    return []

# 拉取所有订阅
async def fetch_all_subs(sources):
    proxies = []
    async with httpx.AsyncClient(timeout=30) as client:
        for url in sources:
            console.print(f"[blue]拉取订阅：{url}[/blue]")
            try:
                resp = await client.get(url)
                text = resp.text.strip()
                subs_proxies = parse_sub_content(text)
                if subs_proxies:
                    console.print(f"[green]成功解析 {len(subs_proxies)} 条节点[/green]")
                else:
                    console.print(f"[yellow]订阅无节点或格式不支持：{url}[/yellow]")
                # 记录订阅节点数量日志
                with open(LOGS_DIR / "subscription_summary.log", "a", encoding="utf-8") as logf:
                    logf.write(f"{url} : {len(subs_proxies)} nodes\n")
                proxies.extend(subs_proxies)
            except Exception as e:
                console.print(f"[red]拉取失败：{url}，{e}[/red]")
                with open(LOGS_DIR / "subscription_summary.log", "a", encoding="utf-8") as logf:
                    logf.write(f"{url} : 拉取失败 {e}\n")
    return proxies

# 验证节点必要字段
def is_valid_node(node):
    required = ["name", "server", "port", "type"]
    return all(k in node and node[k] for k in required)

# 测速函数（下载测速）
async def test_node_speed(node, config, semaphore):
    test_url = config["speed-test-url"]
    timeout_s = config["download-timeout"]
    download_bytes_target = config["download-mb"] * 1024 * 1024
    speed_kbps = 0
    delay_ms = None

    async with semaphore:
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                start = time.perf_counter()
                resp = await client.get(test_url, timeout=timeout_s)
                content_length = 0
                chunk_size = 65536
                async for chunk in resp.aiter_bytes(chunk_size):
                    content_length += len(chunk)
                    elapsed = time.perf_counter() - start
                    if content_length >= download_bytes_target or elapsed >= timeout_s:
                        break
                delay_ms = int((time.perf_counter() - start) * 1000)
                speed_kbps = content_length / 1024 / (elapsed if elapsed > 0 else 1)
                return {
                    "node": node,
                    "delay": delay_ms,
                    "speed_kbps": speed_kbps
                }
        except Exception:
            return {
                "node": node,
                "delay": None,
                "speed_kbps": 0
            }

# 国家Emoji识别
def detect_country_emoji(name):
    flags = {
        "香港": "🇭🇰", "HK": "🇭🇰", "日本": "🇯🇵", "JP": "🇯🇵", "台湾": "🇹🇼",
        "US": "🇺🇸", "美国": "🇺🇸", "SG": "🇸🇬", "新加坡": "🇸🇬", "DE": "🇩🇪",
    }
    for k, emoji in flags.items():
        if k.lower() in name.lower():
            return emoji, k
    return "🏳️", "UNK"

# 重命名节点
def rename_node(node, result, config, idx):
    emoji, country = detect_country_emoji(node["name"])
    speed = f"{result['speed_kbps']/1024:.1f}MB/s" if result['speed_kbps'] > 0 else "0MB/s"
    delay = f"{result['delay']}" if result['delay'] is not None else "timeout"

    # 流媒体标签默认全部用占位符，后续模块更新
    yt = "YT"
    nf = "NF"
    dplus = "D+"
    gpt = "GPT"
    tk = "TK"

    new_name = config["rename-format"].format(
        emoji=emoji,
        country=country,
        id=str(idx).zfill(3),
        speed=speed,
        delay=delay,
        yt=yt,
        nf=nf,
        dplus=dplus,
        gpt=gpt,
        tk=tk
    )
    node["name"] = new_name
    return node

async def main():
    config = load_config()

    # 订阅源从config或硬编码，演示用硬编码
    sources = [
        "https://raw.githubusercontent.com/NiceVPN123/NiceVPN/main/utils/pool/output.yaml",
    ]

    all_nodes = await fetch_all_subs(sources)
    valid_nodes = [n for n in all_nodes if is_valid_node(n)]

    console.print(f"[cyan]共 {len(valid_nodes)} 个节点结构合格，开始测速...[/cyan]")

    semaphore = asyncio.Semaphore(config["concurrent"])
    tasks = [test_node_speed(node, config, semaphore) for node in valid_nodes]

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
        task = progress.add_task("[green]测速中...", total=len(tasks))
        results = []
        for coro in asyncio.as_completed(tasks):
            res = await coro
            results.append(res)
            progress.update(task, advance=1)

    filtered = []
    for idx, res in enumerate(results, 1):
        delay = res["delay"]
        speed = res["speed_kbps"]
        if delay is not None and delay <= config["max-delay"] and speed >= config["min-speed"]:
            renamed = rename_node(res["node"], res, config, idx)
            filtered.append(renamed)

    # 排序
    key = "speed_kbps" if config["sort-by"] == "speed" else "delay"
    filtered.sort(key=lambda x: x.get(key, 0), reverse=True)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        yaml.dump({"proxies": filtered}, f, allow_unicode=True)

    console.print(f"[green]✅ 输出 {len(filtered)} 条合格节点至 {OUTPUT_PATH}[/green]")

if __name__ == "__main__":
    asyncio.run(main())
