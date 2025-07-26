import asyncio
import base64
import yaml
import json
import httpx
import os
from pathlib import Path
from rich.console import Console

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
                console.print(f"[green]成功解析 {len(subs_proxies)} 条节点[/green]")
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
def rename_node(node, config, idx):
    emoji, country = detect_country_emoji(node.get("name", ""))
    speed = "0MB/s"
    delay = "0"

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

    renamed = []
    for idx, node in enumerate(valid_nodes, 1):
        renamed_node = rename_node(node, config, idx)
        renamed.append(renamed_node)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        yaml.dump({"proxies": renamed}, f, allow_unicode=True)

    console.print(f"[green]✅ 输出 {len(renamed)} 条节点至 {OUTPUT_PATH}[/green]")

if __name__ == "__main__":
    asyncio.run(main())
