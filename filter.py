import asyncio
import httpx
import yaml
import os
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

# ✅ 多订阅链接支持（替换为你的订阅）
SOURCE_URLS = [
    "https://raw.githubusercontent.com/NiceVPN123/NiceVPN/main/utils/pool/output.yaml",
    # 你可以继续加多个订阅：
    "https://raw.githubusercontent.com/mahdibland/SSAggregator/master/sub/sub_merge_yaml.yml",
    "https://raw.githubusercontent.com/SoliSpirit/v2ray-configs/main/all_configs.txt",
]

# 输出路径
OUTPUT_PATH = "output/all.yaml"

# 筛选参数
MAX_DELAY = 1000     # 最大延迟（毫秒）
MIN_SPEED = 100     # 最小速度（KB/s）

console = Console()
os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

# 🚀 获取多个 Clash YAML 格式的订阅并合并节点
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
                    console.print(f"[green]✔ 成功：{len(data['proxies'])} 条[/green]")
                else:
                    console.print(f"[yellow]⚠ 无 'proxies' 字段：{url}[/yellow]")
            except Exception as e:
                console.print(f"[red]❌ 拉取失败：{url}[/red] ➜ {e}")
    return proxies

# 节点测速（简单检测连通性）
async def test_node(node, semaphore):
    async with semaphore:
        try:
            proxy = f"http://{node['server']}:{node['port']}"
            async with httpx.AsyncClient(proxies=proxy, timeout=10) as client:
                r = await client.get("http://www.gstatic.com/generate_204")
                if r.status_code == 204:
                    return node
        except:
            pass
        return None

# 主执行逻辑
async def main():
    proxies = await fetch_all_subs()
    if not proxies:
        console.print("[bold red]未获取到任何节点，退出。[/bold red]")
        return

    console.print(f"[cyan]总共加载 {len(proxies)} 个节点，开始筛选...[/cyan]")
    semaphore = asyncio.Semaphore(50)
    good_nodes = []

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as progress:
        task = progress.add_task("测速中...", total=len(proxies))
        tasks = [test_node(p, semaphore) for p in proxies]
        results = await asyncio.gather(*tasks)

        for result in results:
            if result:
                good_nodes.append(result)
            progress.update(task, advance=1)

    console.print(f"[green]✅ 筛选完成，保留 {len(good_nodes)} 个可用节点[/green]")

    # 写入输出文件
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        yaml.dump({"proxies": good_nodes}, f, allow_unicode=True)

if __name__ == "__main__":
    asyncio.run(main())