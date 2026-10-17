from sqlalchemy import Column, DateTime, Integer, String, func, text

from ..database import Base


class Resource(Base):
    """资料下载条目

    之前的版本用代码里的 RESOURCE_CATALOG 数组维护清单，
    管理员要加资料得改代码、重启。改成数据库存之后，
    管理员在系统管理页面就能直接上传、改名、换分类。

    老版本数据无损迁移：首次启动时如果这张表是空的，
    会把 RESOURCE_CATALOG 里的条目全部导进来（见 main.py）。
    """

    __tablename__ = "resources"

    id = Column(Integer, primary_key=True, index=True)
    # 显示名，比如「打印用-示例班名单」
    name = Column(String(200), nullable=False, comment="显示名称")
    # 文件名（磁盘上的文件名，用 UUID 前缀防路径穿越和重名覆盖）
    file_name = Column(String(200), nullable=False, index=True, comment="磁盘文件名")
    # 原始文件名（用户上传时的文件名，仅展示用）
    original_name = Column(String(200), default="", comment="原始文件名")
    # 分类，比如「徽章标志」「班级名单」「常用表格」
    category = Column(String(50), nullable=False, index=True, comment="分类")
    # 排序，数字越小越靠前
    sort_order = Column(Integer, nullable=False, default=0, index=True, comment="排序")
    # 下载次数。资料原来没有任何访问记录，所以没有历史可回填，一律从 0 开始数
    download_count = Column(
        Integer, nullable=False, default=0, server_default=text("0"),
        comment="下载次数",
    )
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")


class ResourceCategory(Base):
    """资料分类的展示顺序

    分类在 resources 表里只是个字符串，本身没有「第几个」的概念。这张表只记
    管理员给分类排的顺序，不记分类本身 —— 页面上出现哪些分类仍然由 resources
    表里实际存在的值决定，一个分类的资料全删光，它自然就不显示了。
    """

    __tablename__ = "resource_categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False, unique=True, index=True, comment="分类名")
    sort_order = Column(Integer, nullable=False, default=0, index=True, comment="排序")

