import asyncio
import base64
import yaml
import json
import httpx
import os
import time
from pathlib import Path
from rich.console import Console

console = Console()
OUTPUT_PATH = "output/all.yaml"
LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)
os.makedirs("output", exist_ok=True)


def load_config():
    with open("config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_sub_content(text):
    text = text.strip()
    try:
        data = yaml.safe_load(text)
        if isinstance(data, dict) and "proxies" in data:
            return data["proxies"]
    except:
        pass

    try:
        decoded = base64.b64decode(text).decode(errors="ignore")
        try:
            data = yaml.safe_load(decoded)
            if isinstance(data, dict) and "proxies" in data:
                return data["proxies"]
        except:
            pass
        try:
            data = json.loads(decoded)
            if "proxies" in data:
                return data["proxies"]
        except:
            pass
    except:
        pass

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    proxies = [{"name": f"Line_{i+1}", "server": "", "port": 0, "type": "unknown", "raw": line} for i, line in enumerate(lines)]
    return proxies


async def fetch_all_subs(sources):
    proxies = []
    async with httpx.AsyncClient(timeout=30) as client:
        for url in sources:
            console.print(f"[blue]拉取订阅：{url}[/blue]")
            try:
                resp = await client.get(url)
                text = resp.text.strip()
                subs_proxies = parse_sub_content(text)
                console.print(f"[green]成功解析 {len(subs_proxies)} 条节点[/green]")
                with open(LOGS_DIR / "subscription_summary.log", "a", encoding="utf-8") as logf:
                    logf.write(f"{url} : {len(subs_proxies)} nodes\n")
                proxies.extend(subs_proxies)
            except Exception as e:
                console.print(f"[red]拉取失败：{url}，{e}[/red]")
                with open(LOGS_DIR / "subscription_summary.log", "a", encoding="utf-8") as logf:
                    logf.write(f"{url} : 拉取失败 {e}\n")
    return proxies


def is_valid_node(node):
    required = ["name", "server", "port", "type"]
    return all(k in node and node[k] for k in required)


def detect_country_emoji(name):
    flags = {
        "香港": "🇭🇰", "HK": "🇭🇰", "日本": "🇯🇵", "JP": "🇯🇵", "台湾": "🇹🇼",
        "US": "🇺🇸", "美国": "🇺🇸", "SG": "🇸🇬", "新加坡": "🇸🇬", "DE": "🇩🇪",
    }
    for k, emoji in flags.items():
        if k.lower() in name.lower():
            return emoji, k
    return "🏳️", "UNK"


async def test_latency(server, port, timeout_ms=3000):
    try:
        start = time.time()
        reader, writer = await asyncio.wait_for(asyncio.open_connection(server, port), timeout=timeout_ms / 1000)
        writer.close()
        await writer.wait_closed()
        return round((time.time() - start) * 1000, 2)
    except:
        return None


def rename_node(node, config, idx, delay_ms=None, unlocked=None):
    emoji, country = detect_country_emoji(node.get("name", ""))
    speed = "0MB/s"
    delay = f"{int(delay_ms)}ms" if delay_ms else "×"

    yt = "YT" if unlocked.get("yt") else "×"
    nf = "NF" if unlocked.get("nf") else "×"
    dplus = "D+" if unlocked.get("dplus") else "×"
    gpt = "GPT" if unlocked.get("gpt") else "×"
    tk = "TK" if unlocked.get("tk") else "×"

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


async def detect_unlocks(node):
    # 模拟结果，后续你可以接入真实探测逻辑
    result = {"yt": True, "nf": True, "dplus": False, "gpt": True, "tk": False}
    return result


async def process_nodes(config, valid_nodes):
    results = []
    semaphore = asyncio.Semaphore(config.get("concurrent", 100))

    async def process(node, idx):
        async with semaphore:
            delay = await test_latency(node["server"], int(node["port"]), timeout_ms=config.get("timeout", 3000))
            if delay is None or delay > config.get("max-delay", 1000):
                return
            unlocked = await detect_unlocks(node)
            renamed_node = rename_node(node, config, idx, delay_ms=delay, unlocked=unlocked)
            results.append(renamed_node)

    await asyncio.gather(*(process(node, idx) for idx, node in enumerate(valid_nodes, 1)))
    return results


async def main():
    config = load_config()
    sources = config.get("subs", [])

    all_nodes = await fetch_all_subs(sources)
    console.print(f"[bold blue]拉取到节点总数: {len(all_nodes)}[/bold blue]")

    valid_nodes = [n for n in all_nodes if is_valid_node(n)]
    console.print(f"[bold green]结构合格节点数: {len(valid_nodes)}[/bold green]")

    filtered_nodes = await process_nodes(config, valid_nodes)
    console.print(f"[bold yellow]最终输出节点数: {len(filtered_nodes)}[/bold yellow]")

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        yaml.dump({"proxies": filtered_nodes}, f, allow_unicode=True)

    console.print(f"[green]✅ 输出至 {OUTPUT_PATH} 完成[/green]")

if __name__ == "__main__":
    asyncio.run(main())
