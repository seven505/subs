import asyncio
import httpx
import yaml
import os
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

# 参数配置
SOURCE_URL = "https://raw.githubusercontent.com/NiceVPN123/NiceVPN/main/utils/pool/output.yaml"
OUTPUT_PATH = "output/all.yaml"
MAX_DELAY = 500  # ms
MIN_SPEED = 100  # KB/s

console = Console()

# 创建输出目录
os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

# 读取远程 Clash 订阅
async def fetch_subscribe():
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(SOURCE_URL)
        return yaml.safe_load(r.text)

# 测速模拟
async def test_node(node, semaphore):
    async with semaphore:
        name = node.get("name", "未知节点")
        try:
            async with httpx.AsyncClient(timeout=10, http2=True) as client:
                r = await client.get("https://www.google.com/generate_204", proxy=f"http://{node['server']}:{node['port']}")
                if r.status_code == 204:
                    return node
        except Exception:
            pass
        return None

# 入口主函数
async def main():
    data = await fetch_subscribe()
    proxies = data.get("proxies", [])
    if not proxies:
        console.print("[bold red]没有获取到任何节点[/bold red]")
        return

    console.print(f"[cyan]共获取到 {len(proxies)} 个节点，开始测试...[/cyan]")

    good_nodes = []
    semaphore = asyncio.Semaphore(50)

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as progress:
        task = progress.add_task("测速中...", total=len(proxies))
        tasks = []
        for node in proxies:
            tasks.append(test_node(node, semaphore))

        results = await asyncio.gather(*tasks)
        for r in results:
            if r:
                good_nodes.append(r)
            progress.update(task, advance=1)

    console.print(f"[green]筛选完成，共 {len(good_nodes)} 个合格节点[/green]")

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        yaml.dump({"proxies": good_nodes}, f, allow_unicode=True)

if __name__ == "__main__":
    asyncio.run(main())
