"""
EdgeOne Makers部署脚本
=====================
将生成的HTML报告部署到EdgeOne Makers，获得固定URL。

前置条件：
1. 注册腾讯云账号（免费）：https://cloud.tencent.com/
2. 开通EdgeOne Makers：https://console.cloud.tencent.com/edgeone/pages
3. 获取API Token：https://console.cloud.tencent.com/edgeone/apikey

使用方式：
  # 方式1：通过环境变量
  export EDGEONE_API_TOKEN="your-token-here"
  python3 scripts/deploy_edgeone.py

  # 方式2：通过命令行参数
  python3 scripts/deploy_edgeone.py --token "your-token-here"

  # 方式3：交互式输入
  python3 scripts/deploy_edgeone.py
"""
import os
import sys
import subprocess
import argparse
import logging
from pathlib import Path
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PROJECT_NAME = "water-eco-daily"
SITE_DIR = "/workspace/water-eco-kb/output/site"


def deploy(token: str):
    """部署HTML到EdgeOne Makers"""
    if not os.path.exists(SITE_DIR):
        logger.error(f"站点目录不存在: {SITE_DIR}")
        logger.error("请先运行: python3 scripts/generate_report.py")
        return False

    # 确保有index.html
    index_file = os.path.join(SITE_DIR, "index.html")
    if not os.path.exists(index_file):
        logger.error(f"index.html不存在: {index_file}")
        return False

    # 归档当前报告到archive目录
    archive_dir = os.path.join(SITE_DIR, "archive")
    os.makedirs(archive_dir, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    archive_file = os.path.join(archive_dir, f"{today}.html")
    
    # 复制当前报告到归档
    import shutil
    shutil.copy2(index_file, archive_file)
    logger.info(f"已归档: {archive_file}")

    # 执行EdgeOne部署
    logger.info(f"开始部署到EdgeOne Makers (项目: {PROJECT_NAME})...")
    cmd = [
        "edgeone", "makers", "deploy", SITE_DIR,
        "-n", PROJECT_NAME,
        "-t", token,
        "-e", "production",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    if result.returncode == 0:
        logger.info("部署成功!")
        # 从输出中提取URL
        output = result.stdout + result.stderr
        logger.info(f"部署输出: {output[:500]}")
        
        # 尝试提取URL
        for line in output.split("\n"):
            if "http" in line and ("edgeone" in line or "makers" in line):
                logger.info(f"访问地址: {line.strip()}")
                break
        
        return True
    else:
        logger.error(f"部署失败: {result.stderr[:300]}")
        logger.error(f"stdout: {result.stdout[:300]}")
        return False


def main():
    parser = argparse.ArgumentParser(description="部署HTML报告到EdgeOne Makers")
    parser.add_argument("--token", default=None, help="EdgeOne API Token")
    args = parser.parse_args()

    token = args.token or os.environ.get("EDGEONE_API_TOKEN", "")

    if not token:
        print("\n" + "=" * 60)
        print("  EdgeOne Makers 部署需要API Token")
        print("=" * 60)
        print("\n  获取步骤：")
        print("  1. 注册腾讯云账号：https://cloud.tencent.com/")
        print("  2. 开通EdgeOne Makers：https://console.cloud.tencent.com/edgeone/pages")
        print("  3. 获取API Token：在EdgeOne控制台 → API Token管理")
        print("\n  使用方式：")
        print("  export EDGEONE_API_TOKEN='your-token'")
        print("  python3 scripts/deploy_edgeone.py")
        print("\n" + "=" * 60 + "\n")
        
        token = input("请输入EdgeOne API Token（或按Enter跳过）: ").strip()
        if not token:
            print("已跳过部署。请获取Token后重新运行。")
            return

    success = deploy(token)
    if success:
        print("\n✅ 部署成功！团队成员可通过固定URL访问每日资讯。")
    else:
        print("\n❌ 部署失败，请检查Token和网络。")
        sys.exit(1)


if __name__ == "__main__":
    main()
