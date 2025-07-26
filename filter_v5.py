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

# --- 读取配置 ---
def load_config():
    with open("config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)

# --- 解析订阅内容 ---
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

# --- 拉取所有订阅 ---
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
                proxies.extend(subs_proxies)
            except Exception as e:
                console.print(f"[red]拉取失败：{url}，{e}[/red]")
    return proxies

# --- 校验节点必须字段 ---
def is_valid_node(node):
    required = ["name", "server", "port", "type"]
    return all(k in node and node[k] for k in required)

# --- 生成代理字典供 httpx ---
def node_to_proxy(node):
    server = node["server"]
    port = node["port"]
    # 这里简化，统一用 socks5 代理格式，你可根据节点类型改写
    proxy_url = f"socks5://{server}:{port}"
    return {"http": proxy_url, "https": proxy_url}

# --- 通过 TCP 连接测试延迟 ---
async def test_latency(server, port, timeout_ms=3000):
    try:
        start = time.time()
        reader, writer = await asyncio.wait_for(asyncio.open_connection(server, port), timeout=timeout_ms / 1000)
        writer.close()
        await writer.wait_closed()
        return round((time.time() - start) * 1000, 2)
    except:
        return None

# --- 下载测速（用测速地址，返回MB/s） ---
async def test_speed(proxies, test_url, download_mb=10, timeout=15):
    try:
        async with httpx.AsyncClient(proxies=proxies, timeout=timeout) as client:
            resp = await client.get(test_url, timeout=timeout)
            content = resp.content[:download_mb * 1024 * 1024]
            speed_mb_s = len(content) / (1024 * 1024) / resp.elapsed.total_seconds()
            return round(speed_mb_s, 2)
    except:
        return 0.0

# --- 流媒体解锁检测（调用下面方法） ---
async def check_gpt(proxy, timeout=10):
    url = "https://chat.openai.com/"
    try:
        async with httpx.AsyncClient(proxies=proxy, timeout=timeout, verify=False) as client:
            r = await client.get(url)
            return r.status_code == 200
    except:
        return False

async def check_youtube(proxy, timeout=10):
    url = "https://www.youtube.com/premium"
    try:
        async with httpx.AsyncClient(proxies=proxy, timeout=timeout, verify=False) as client:
            r = await client.get(url)
            return r.status_code == 200 and "Premium" in r.text
    except:
        return False

async def check_netflix(proxy, timeout=10):
    url = "https://www.netflix.com/title/81215567"
    try:
        async with httpx.AsyncClient(proxies=proxy, timeout=timeout, verify=False) as client:
            r = await client.get(url)
            return r.status_code == 200 and "unavailable" not in r.text.lower()
    except:
        return False

async def check_disney(proxy, timeout=10):
    url = "https://www.disneyplus.com/"
    try:
        async with httpx.AsyncClient(proxies=proxy, timeout=timeout, verify=False) as client:
            r = await client.get(url)
            return r.status_code == 200
    except:
        return False

async def check_tiktok(proxy, timeout=10):
    url = "https://www.tiktok.com/"
    try:
        async with httpx.AsyncClient(proxies=proxy, timeout=timeout, verify=False) as client:
            r = await client.get(url)
            return r.status_code == 200
    except:
        return False

async def detect_unlocks(proxy, timeout=10):
    results = await asyncio.gather(
        check_gpt(proxy, timeout),
        check_youtube(proxy, timeout),
        check_netflix(proxy, timeout),
        check_disney(proxy, timeout),
        check_tiktok(proxy, timeout),
        return_exceptions=True
    )
    keys = ["gpt", "yt", "nf", "dplus", "tk"]
    unlocked = {}
    for k, r in zip(keys, results):
        unlocked[k] = r if isinstance(r, bool) else False
    return unlocked

# --- 节点命名格式 ---
def detect_country_emoji(name):
    flags = {
        "香港": "🇭🇰", "HK": "🇭🇰", "日本": "🇯🇵", "JP": "🇯🇵", "台湾": "🇹🇼",
        "US": "🇺🇸", "美国": "🇺🇸", "SG": "🇸🇬", "新加坡": "🇸🇬", "DE": "🇩🇪",
    }
    for k, emoji in flags.items():
        if k.lower() in name.lower():
            return emoji, k
    return "🏳️", "UNK"

def rename_node(node, config, idx, delay_ms=None, speed_mb=0.0, unlocked=None):
    emoji, country = detect_country_emoji(node.get("name", ""))
    delay = f"{int(delay_ms)}ms" if delay_ms else "×"

    yt = "YT" if unlocked.get("yt") else "×"
    nf = "NF" if unlocked.get("nf") else "×"
    dplus = "D+" if unlocked.get("dplus") else "×"
    gpt = "GPT" if unlocked.get("gpt") else "×"
    tk = "TK" if unlocked.get("tk") else "×"

    speed_str = f"{speed_mb:.2f}MB/s" if speed_mb else "0MB/s"

    new_name = config.get("rename-format", "{emoji}{country}_{id} |{speed}|{delay}|{yt}|{nf}|{dplus}|{gpt}|{tk}").format(
        emoji=emoji,
        country=country,
        id=str(idx).zfill(3),
        speed=speed_str,
        delay=delay,
        yt=yt,
        nf=nf,
        dplus=dplus,
        gpt=gpt,
        tk=tk
    )
    node["name"] = new_name
    return node

# --- 并发处理节点 ---
async def process_node(node, idx, config):
    delay = await test_latency(node["server"], int(node["port"]), timeout_ms=config.get("timeout", 5000))
    if delay is None or delay > config.get("max-delay", 1000):
        return None

    proxies = node_to_proxy(node)
    speed = await test_speed(proxies, config.get("speed-test-url", "https://github.com/AaronFeng753/Waifu2x-Extension-GUI/releases/download/v2.21.12/Waifu2x-Extension-GUI-v2.21.12-Portable.7z"), download_mb=config.get("download-mb", 10))
    if speed < config.get("min-speed", 0.5):
        return None

    unlocked = await detect_unlocks(proxies, timeout=10)
    renamed = rename_node(node, config, idx, delay_ms=delay, speed_mb=speed, unlocked=unlocked)
    return renamed

# --- 主入口 ---
async def main():
    config = load_config()
    sources = config.get("subs", [])

    all_nodes = await fetch_all_subs(sources)
    console.print(f"[bold blue]拉取到节点总数: {len(all_nodes)}[/bold blue]")

    valid_nodes = [n for n in all_nodes if is_valid_node(n)]
    console.print(f"[bold green]结构合格节点数: {len(valid_nodes)}[/bold green]")

    semaphore = asyncio.Semaphore(config.get("concurrent", 100))

    async def sem_task(node, idx):
        async with semaphore:
            return await process_node(node, idx, config)

    tasks = [sem_task(node, idx) for idx, node in enumerate(valid_nodes, 1)]
    results = await asyncio.gather(*tasks)
    filtered_nodes = [node for node in results if node is not None]

    console.print(f"[bold yellow]最终输出节点数: {len(filtered_nodes)}[/bold yellow]")

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        yaml.dump({"proxies": filtered_nodes}, f, allow_unicode=True)

    # 写日志
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    percent = round((len(filtered_nodes) / len(all_nodes)) * 100, 2) if len(all_nodes) else 0
    log_line = f"【{now}】总节点数={len(all_nodes)}，结构合格节点数={len(valid_nodes)}，成功节点数={len(filtered_nodes)}，成功占比={percent}%\n"
    Path("logs").mkdir(exist_ok=True)
    with open("logs/run_summary.log", "a", encoding="utf-8") as logf:
        logf.write(log_line)
    console.print(log_line)

if __name__ == "__main__":
    asyncio.run(main())
