"""
tdrive云盘客户端 - 管理知识库目录映射和文件上传辅助

注意：实际的tdrive文件操作通过MCP工具完成（tdrive.dir_create, tdrive.file_upload等）。
本模块负责管理目录ID映射、文件命名规范和上传队列。
"""
import json
import logging
from pathlib import Path
from typing import Dict, Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)

# tdrive根目录ID
TDRIVE_ROOT_ID = "CWPEgbUECHEU"

# 知识库目录结构定义
DIRECTORY_STRUCTURE = {
    "01_政策法规标准": {
        "sub_dirs": {"国家级": "", "省级_浙江": "", "市级_杭州": "", "国际": ""}
    },
    "02_研究文献": {
        "sub_dirs": {"国内": "", "国际": ""}
    },
    "03_领导讲话": {"sub_dirs": {}},
    "04_技术产品": {"sub_dirs": {}},
    "05_实践案例": {
        "sub_dirs": {"工程案例": "", "技术案例": "", "管理案例": ""}
    },
    "06_专家团队": {"sub_dirs": {}},
    "07_科研院所与企业": {"sub_dirs": {}},
    "08_每日资讯": {
        "sub_dirs": {}
    },
    "09_知识图谱": {"sub_dirs": {}},
    "99_系统配置": {"sub_dirs": {}},
}


class TdriveClient:
    """tdrive云盘客户端 - 目录映射管理"""

    MAPPING_FILE = "/workspace/water-eco-kb/config/tdrive_dirs.json"

    def __init__(self):
        self.dir_mapping: Dict[str, str] = {}
        self._load_mapping()

    def _load_mapping(self):
        """加载目录ID映射"""
        path = Path(self.MAPPING_FILE)
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                self.dir_mapping = json.load(f)
            logger.info(f"加载tdrive目录映射: {len(self.dir_mapping)} 个目录")

    def _save_mapping(self):
        """保存目录ID映射"""
        Path(self.MAPPING_FILE).parent.mkdir(parents=True, exist_ok=True)
        with open(self.MAPPING_FILE, "w", encoding="utf-8") as f:
            json.dump(self.dir_mapping, f, ensure_ascii=False, indent=2)

    def set_dir_id(self, category: str, dir_id: str, sub_category: str = ""):
        """设置目录ID"""
        key = f"{category}/{sub_category}" if sub_category else category
        self.dir_mapping[key] = dir_id
        self._save_mapping()

    def get_dir_id(self, category: str, sub_category: str = "") -> Optional[str]:
        """获取分类对应的tdrive目录ID"""
        key = f"{category}/{sub_category}" if sub_category else category
        dir_id = self.dir_mapping.get(key)
        if not dir_id:
            # 尝试只用一级分类
            dir_id = self.dir_mapping.get(category)
        return dir_id

    @staticmethod
    def generate_filename(doc: Dict) -> str:
        """根据文档元数据生成规范文件名"""
        date_str = doc.get("publish_date", datetime.now().strftime("%Y-%m-%d"))
        title = doc.get("title", "未命名")[:30]
        # 清理文件名中的非法字符
        safe_title = "".join(c for c in title if c.isalnum() or c in "._-中文")
        quality = doc.get("quality_score", 0.5)
        return f"{date_str}_{safe_title}_Q{quality:.1f}.md"

    def get_upload_instructions(self, doc: Dict) -> Dict:
        """
        生成文件上传指令（供Agent执行MCP工具调用）
        返回包含目标目录ID、文件名、本地路径等信息
        """
        category = doc.get("category", "02_研究文献")
        sub_category = doc.get("sub_category", "")
        dir_id = self.get_dir_id(category, sub_category)

        return {
            "dir_id": dir_id,
            "category": category,
            "sub_category": sub_category,
            "filename": self.generate_filename(doc),
            "title": doc.get("title", ""),
            "content": doc.get("content", ""),
            "url": doc.get("url", ""),
        }

    def get_all_categories(self) -> List[str]:
        """获取所有需要创建的目录（含子目录）"""
        dirs = []
        for cat, info in DIRECTORY_STRUCTURE.items():
            dirs.append(cat)
            for sub in info.get("sub_dirs", {}):
                dirs.append(f"{cat}/{sub}")
        return dirs

    def is_initialized(self) -> bool:
        """检查tdrive目录是否已初始化"""
        return len(self.dir_mapping) >= 10  # 至少10个一级目录
