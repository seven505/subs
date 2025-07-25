import asyncio
import httpx
import yaml
import os
import time
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

# ✅ 订阅链接列表（支持多个）
SOURCE_URLS = [
    "https://raw.githubusercontent.com/NiceVPN123/NiceVPN/main/utils/pool/output.yaml",
    "https://raw.githubusercontent.com/gfpcom/free-proxy-list/main/list/trojan.txt"
]

# ✅ 允许的协议类型
ALLOWED_TYPES = ["vmess", "vless", "ss", "trojan", "hysteria2", "tuic"]

# ✅ 延迟筛选阈值（毫秒）
MAX_LATENCY_MS = 1000

# ✅ 输出文件路径
OUTPUT_PATH = "output/all.yaml"

console = Console()
os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)


# 🚀 拉取所有订阅合并 proxies
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
                    console.print(f"[yellow]⚠ 无 'proxies' 字段：{url}[/yellow]")
            except Exception as e:
                console.print(f"[red]❌ 拉取失败：{url} ➜ {e}[/red]")
    return proxies


# ✅ 节点结构检查
def is_valid_node(node):
    required = ["name", "server", "port", "type"]
    return all(k in node and node[k] for k in required) and node["type"] in ALLOWED_TYPES


# 🚀 测试延迟（连接 TCP 判断通不通 + 记录时间）
async def test_latency(node, semaphore):
    host = node["server"]
    port = int(node["port"])
    start = time.perf_counter()

    async with semaphore:
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=3)
            latency = int((time.perf_counter() - start) * 1000)
            writer.close()
            await writer.wait_closed()
            return node if latency <= MAX_LATENCY_MS else None
        except:
            return None


# 🎯 主流程
async def main():
    raw_proxies = await fetch_all_subs()
    valid_nodes = [p for p in raw_proxies if is_valid_node(p)]

    console.print(f"[cyan]共 {len(valid_nodes)} 个结构合格节点，开始延迟测速...[/cyan]")

    good_nodes = []
    semaphore = asyncio.Semaphore(100)

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as progress:
        task = progress.add_task("测速中...", total=len(valid_nodes))
        tasks = [test_latency(p, semaphore) for p in valid_nodes]
        results = await asyncio.gather(*tasks)

        for r in results:
            if r:
                good_nodes.append(r)
            progress.update(task, advance=1)

    console.print(f"[green]✅ 延迟筛选完成，保留 {len(good_nodes)} 个节点 ≤ {MAX_LATENCY_MS}ms[/green]")

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        yaml.dump({"proxies": good_nodes}, f, allow_unicode=True)


if __name__ == "__main__":
    asyncio.run(main())