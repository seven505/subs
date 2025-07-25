import asyncio
import httpx
import yaml
import os
from rich.console import Console
from rich.table import Table

# ✅ 多个订阅链接（可扩展）
SOURCE_URLS = [
    "https://raw.githubusercontent.com/NiceVPN123/NiceVPN/main/utils/pool/output.yaml",
    "",
]

# 合格协议类型
ALLOWED_TYPES = ["vmess", "vless", "ss", "trojan", "hysteria2", "tuic"]

# 输出路径
OUTPUT_PATH = "output/all.yaml"

console = Console()
os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

# 🚀 拉取所有订阅并合并 proxies
async def fetch_all_subs():
    proxies = []
    async with httpx.AsyncClient(timeout=15) as client:
        for url in SOURCE_URLS:
            try:
                console.print(f"[blue]正在拉取订阅：{url}[/blue]")
                r = await client.get(url)
                data = yaml.safe_load(r.text)
                if "proxies" in data:
                    count = len(data["proxies"])
                    proxies.extend(data["proxies"])
                    console.print(f"[green]✔ 成功加载 {count} 条节点[/green]")
                else:
                    console.print(f"[yellow]⚠ 无 'proxies' 字段：{url}[/yellow]")
            except Exception as e:
                console.print(f"[red]❌ 拉取失败：{url}[/red] ➜ {e}")
    return proxies

# ✅ 节点结构判断
def is_valid_node(node):
    required = ["name", "server", "port", "type"]
    return all(key in node and node[key] for key in required)

# 🎯 筛选主逻辑
async def main():
    proxies = await fetch_all_subs()
    if not proxies:
        console.print("[bold red]没有抓取到任何节点[/bold red]")
        return

    valid_nodes = []
    for node in proxies:
        if is_valid_node(node) and node["type"] in ALLOWED_TYPES:
            valid_nodes.append(node)

    table = Table(title="节点筛选结果")
    table.add_column("协议", justify="center")
    table.add_column("节点数", justify="right")

    stats = {}
    for node in valid_nodes:
        t = node["type"]
        stats[t] = stats.get(t, 0) + 1

    for t, count in stats.items():
        table.add_row(t, str(count))

    console.print(table)

    # ✍️ 写入输出文件
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        yaml.dump({"proxies": valid_nodes}, f, allow_unicode=True)

    console.print(f"[bold green]✅ 筛选完成，共输出 {len(valid_nodes)} 条合格节点到 [cyan]{OUTPUT_PATH}[/cyan][/bold green]")

if __name__ == "__main__":
    asyncio.run(main())