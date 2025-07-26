import asyncio
import base64
import yaml
import json
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

# 解析订阅，支持 yaml / base64 txt / json / 纯文本节点列表
def parse_sub_content(text):
    text = text.strip()

    # 1. 直接yaml解析
    try:
        data = yaml.safe_load(text)
        if isinstance(data, dict) and "proxies" in data:
            return data["proxies"]
    except Exception:
        pass

    # 2. base64解码后尝试yaml/json解析
    try:
        decoded = base64.b64decode(text).decode(errors='ignore')
        # 再尝试yaml
        try:
            data = yaml.safe_load(decoded)
            if isinstance(data, dict) and "proxies" in data:
                return data["proxies"]
        except Exception:
            pass
        # 尝试json
        try:
            data = json.loads(decoded)
            if "proxies" in data:
                return data["proxies"]
        except Exception:
            pass
    except Exception:
        pass

    # 3. 纯文本节点列表（ss/ssr/vmess链接行）
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines:
        proxies = []
        for i, line in enumerate(lines):
            proxies.append({"name": f"Line_{i+1}", "server": "", "port": 0, "type": "unknown", "raw": line})
        return proxies

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
                console.print(f"[blue]订阅内容前200字符: {text[:200]}[/blue]")
                subs_proxies = parse_sub_content(text)
                if subs_proxies:
                    console.print(f"[green]成功解析 {len(subs_proxies)} 条节点[/green]")
                else:
                    console.print(f"[yellow]订阅无节点或格式不支持：{url}[/yellow]")
                with open(LOGS_DIR / "subscription_summary.log", "a", encoding="utf-8") as logf:
                    logf.write(f"{url} : {len(subs_proxies)} nodes\n")
                proxies.extend(subs_proxies)
            except Exception as e:
                console.print(f"[red]拉取失败：{url}，{e}[/red]")
                with open(LOGS_DIR / "subscription_summary.log", "a", encoding="utf-8") as logf:
                    logf.write(f"{url} : 拉取失败 {e}\n")
    return proxies

# 验证节点字段完整性
def is_valid_node(node):
    required = ["name", "server", "port", "type"]
    return all(k in node and node[k] for k in required)

# 测速函数，修复 elapsed 未定义问题
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
                elapsed = 0  # 确保已初始化
                async for chunk in resp.aiter_bytes(chunk_size):
                    content_length += len(chunk)
                    elapsed = time.perf_counter() - start
                    if content_length >= download_bytes_target or elapsed >= timeout_s:
                        break
                delay_ms = int(elapsed * 1000)
                speed_kbps = content_length / 1024 / (elapsed if elapsed > 0 else 1)
                return {
                    "node": node,
                    "delay": delay_ms,
                    "speed_kbps": speed_kbps
                }
        except Exception as e:
            console.print(f"[red]测速异常: {e}[/red]")
            return {
                "node": node,
                "delay": None,
                "speed_kbps": 0
            }

# 国家 Emoji 映射
def detect_country_emoji(name):
    flags = {
        "香港": "🇭🇰", "HK": "🇭🇰", "日本": "🇯🇵", "JP": "🇯🇵", "台湾": "🇹🇼",
        "US": "🇺🇸", "美国": "🇺🇸", "SG": "🇸🇬", "新加坡": "🇸🇬", "DE": "🇩🇪",
    }
    for k, emoji in flags.items():
        if k.lower() in name.lower():
            return emoji, k
    return "🏳️", "UNK"

# 节点命名规则
def rename_node(node, result, config, idx):
    emoji, country = detect_country_emoji(node.get("name", ""))
    speed = f"{result['speed_kbps']/1024:.1f}MB/s" if result['speed_kbps'] > 0 else "0MB/s"
    delay = f"{result['delay']}" if result['delay'] is not None else "timeout"

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

# 主流程
async def main():
    config = load_config()
    sources = config.get("subs", [])

    all_nodes = await fetch_all_subs(sources)
    console.print(f"[bold blue]拉取到节点总数: {len(all_nodes)}[/bold blue]")

    valid_nodes = [n for n in all_nodes if is_valid_node(n)]
    console.print(f"[bold green]结构合格节点数: {len(valid_nodes)}[/bold green]")

    if not valid_nodes:
        console.print("[red]没有符合格式的节点，退出[/red]")
        return

    console.print(f"[cyan]开始测速...[/cyan]")
    semaphore = asyncio.Semaphore(config.get("concurrent", 50))
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
        if delay is not None and delay <= config.get("max-delay", 5000) and speed >= config.get("min-speed", 1024):
            renamed = rename_node(res["node"], res, config, idx)
            filtered.append(renamed)

    # 排序输出
    key = "speed_kbps" if config.get("sort-by", "speed") == "speed" else "delay"
    filtered.sort(key=lambda x: x.get(key, 0), reverse=True)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        yaml.dump({"proxies": filtered}, f, allow_unicode=True)

    console.print(f"[green]✅ 输出 {len(filtered)} 条合格节点至 {OUTPUT_PATH}[/green]")

if __name__ == "__main__":
    asyncio.run(main())