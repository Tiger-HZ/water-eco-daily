"""
邮件通知脚本
============
每日采集和部署完成后，发送邮件通知到 tjhjxhlin@163.com

使用方式：
  python3 scripts/send_email.py [--url https://water-eco-daily.edgeone.app]

需要配置SMTP：
  方式1：在 config/settings.yaml 中配置 email
  方式2：通过环境变量 SMTP_HOST, SMTP_USER, SMTP_PASS
"""
import os
import sys
import smtplib
import logging
import argparse
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# 邮件配置
RECIPIENT_EMAIL = "tjhjxhlin@163.com"
DEFAULT_SMTP_HOST = "smtp.163.com"
DEFAULT_SMTP_PORT = 465
DEFAULT_SMTP_USER = "tjhjxhlin@163.com"  # 163邮箱SMTP用户名


def send_email(site_url: str = "", stats: dict = None):
    """发送每日资讯通知邮件"""
    # 从环境变量或默认值获取SMTP配置
    smtp_host = os.environ.get("SMTP_HOST", DEFAULT_SMTP_HOST)
    smtp_port = int(os.environ.get("SMTP_PORT", DEFAULT_SMTP_PORT))
    smtp_user = os.environ.get("SMTP_USER", DEFAULT_SMTP_USER)
    smtp_pass = os.environ.get("SMTP_PASS", "")  # 需要配置163邮箱授权码

    if not smtp_pass:
        logger.warning("SMTP密码未配置，请设置环境变量 SMTP_PASS")
        logger.warning("163邮箱授权码获取：设置 → POP3/SMTP/IMAP → 开启SMTP → 生成授权码")
        return False

    today = datetime.now().strftime("%Y年%m月%d日")
    
    # 构建邮件内容
    total = stats.get("total", 0) if stats else 0
    high_quality = stats.get("quality_dist", {}).get("高质量", 0) if stats else 0
    categories = stats.get("by_category", {}) if stats else {}
    
    category_text = "\n".join(f"  • {k}: {v} 篇" for k, v in categories.items()) if categories else "  暂无数据"
    
    html_content = f"""
    <html>
    <body style="font-family: 'Microsoft YaHei', sans-serif; padding: 20px;">
        <h2 style="color: #0c4a6e;">水生态环境资讯日报 - {today}</h2>
        <p>您好，今日水生态环境资讯已更新完成。</p>
        
        <h3 style="color: #0891b2;">📊 今日统计</h3>
        <ul>
            <li>总文档数: <strong>{total}</strong> 篇</li>
            <li>高质量文献: <strong>{high_quality}</strong> 篇</li>
        </ul>
        
        <h3 style="color: #0891b2;">📂 分类分布</h3>
        <pre style="background: #f0f9ff; padding: 10px; border-radius: 5px;">{category_text}</pre>
        
        {"<h3 style='color: #0891b2;'>🔗 访问地址</h3><p><a href='" + site_url + "' style='color: #0891b2; font-size: 16px;'>" + site_url + "</a></p>" if site_url else ""}
        
        <hr style="border: 1px solid #e0f2fe; margin: 20px 0;">
        <p style="color: #64748b; font-size: 12px;">
            本邮件由水生态环境知识管理系统自动发送<br>
            如有建议或反馈，请回复本邮件或访问资讯页面留言
        </p>
    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"水生态环境资讯日报 - {today}"
    msg["From"] = smtp_user
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        logger.info(f"发送邮件到 {RECIPIENT_EMAIL}...")
        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port)
            server.starttls()
        
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, [RECIPIENT_EMAIL], msg.as_string())
        server.quit()
        logger.info("邮件发送成功!")
        return True
    except Exception as e:
        logger.error(f"邮件发送失败: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="发送每日资讯邮件通知")
    parser.add_argument("--url", default="", help="资讯页面URL")
    args = parser.parse_args()

    # 从数据库获取统计
    try:
        sys.path.insert(0, "/workspace/water-eco-kb")
        from src.storage.metadata_db import MetadataDB
        db = MetadataDB("/workspace/water-eco-kb/data/metadata.db")
        stats = db.get_stats()
    except Exception:
        stats = None

    send_email(args.url, stats)


if __name__ == "__main__":
    main()
