import os
import subprocess
import yaml
import json
from pathlib import Path
from datetime import datetime

# === 加载配置 ===
with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

SUBS_CHECK_BIN = "./subs-check-bin/subs-check"
CONFIG_FILE = "subs-check-config.yaml"
RAW_RESULT_JSON = "result.json"
OUTPUT_FILE = config.get("output_file", "output/all.yaml")

# === 1. 生成 subs-check 专用 config 文件 ===
subs_config = {
    "subscriptions": config["subscribe_urls"],
    "checkItems": ["latency", "youtube", "netflix", "chatgpt", "tiktok"],
    "settings": {
        "timeout": config.get("timeout", 5000),
        "concurrent": config.get("concurrent", 40),
        "minSpeed": config.get("min-speed", 0.5),
        "maxLatency": config.get("max-delay", 1000),
        "downloadTest": {
            "timeout": config.get("download-timeout", 10),
            "sizeInMB": config.get("download-mb", 5),
            "url": config.get("speed-test-url")
        },
        "output": RAW_RESULT_JSON
    }
}
with open(CONFIG_FILE, "w", encoding="utf-8") as f:
    yaml.dump(subs_config, f)

print("✅ subs-check 配置文件生成完成")

# === 2. 运行 subs-check ===
print("🚀 开始运行 subs-check")
subprocess.run([SUBS_CHECK_BIN, "run", "-c", CONFIG_FILE], check=True)
print("✅ subs-check 执行完成")

# === 3. 读取测速结果 JSON ===
with open(RAW_RESULT_JSON, "r", encoding="utf-8") as f:
    data = json.load(f)

proxies = []
success = 0

for idx, item in enumerate(data.get("proxies", [])):
    if item.get("available"):
        success += 1
        name = config["rename-format"].format(
            emoji=item.get("emoji", "🏳️"),
            country=item.get("countryCode", "UNK"),
            id=str(idx).zfill(3),
            speed=f"{item.get('speed', 0):.1f}MB/s",
            delay=item.get("latency", 999),
            yt="YT" if item.get("youtube", False) else "×",
            nf="NF" if item.get("netflix", False) else "×",
            dplus="D+" if item.get("disneyplus", False) else "×",
            gpt="GPT" if item.get("chatgpt", False) else "×",
            tk="TK" if item.get("tiktok", False) else "×",
        )

        node = item.get("rawConfig", {})
        node["name"] = name
        proxies.append(node)

# === 4. 写入 clash 节点文件 ===
Path(OUTPUT_FILE).parent.mkdir(parents=True, exist_ok=True)
with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    yaml.dump({"proxies": proxies}, f, allow_unicode=True)

# === 5. 输出日志信息 ===
now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
total = len(data.get("proxies", []))
print(f"📊 [{now}] 总节点数={total} 成功节点数={success} 成功率={(success/total*100 if total else 0):.2f}%")
print(f"📁 clash 节点已写入：{OUTPUT_FILE}")
