"""生成 L3 E2E 验收测试用的 bidder ZIP fixture。

运行: cd backend && uv run python ../e2e/fixtures/gen_test_bidders.py

产出:
  e2e/fixtures/bidder-a.zip  (技术方案 + 投标函 + 报价清单)
  e2e/fixtures/bidder-b.zip  (技术方案与 A 共享 6 段文本, 触发相似度检测)
"""

from __future__ import annotations

import sys
import zipfile
from datetime import datetime
from pathlib import Path

# 让 import 能找到 backend 代码
backend_root = Path(__file__).resolve().parent.parent.parent / "backend"
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tests" / "fixtures"))

from doc_fixtures import make_real_docx, make_price_xlsx  # noqa: E402

FIXTURE_DIR = Path(__file__).resolve().parent
TMP = FIXTURE_DIR / "_tmp_gen"

# ── 共享文本段落（触发 text_similarity，总字符数需超过 MIN_DOC_CHARS=500） ──
SHARED_PARAGRAPHS = [
    "本技术方案严格按照招标文件的要求编制，充分考虑了项目的实际情况和技术难点，针对施工现场的地质条件、气候特征、周边环境等因素进行了详细分析和论证。",
    "施工过程中将采用先进的信息化管理系统，包括BIM三维建模技术、无人机巡检系统和智慧工地平台，实现对进度、质量、安全、成本的全方位动态监控和实时预警。",
    "项目团队由具有丰富经验的高级工程师组成，项目经理持有一级建造师证书，总工程师具有二十年以上同类工程经验，确保工程质量达到国家一级标准和行业领先水平。",
    "我公司承诺在合同工期内完成全部施工任务，并提供五年质量保修服务。保修期内发生的任何质量问题，我方将在接到通知后二十四小时内到场处理，七个工作日内完成修复。",
    "安全生产管理方面，将严格执行国家安全生产法律法规，建立健全安全管理体系，设立专职安全员并配备完善的安全防护设施，确保施工期间零重大安全事故目标的实现。",
    "环境保护措施包括施工扬尘治理、噪音控制、废水处理和固体废弃物分类回收等，全面落实绿色施工要求，最大限度减少施工活动对周边居民生活和自然环境的影响。",
    "本方案特别重视冬季和雨季施工的质量保障措施，制定了详细的混凝土养护方案和防雨排水预案，确保不同气候条件下的施工质量均能满足设计和规范要求。",
    "我方将严格执行材料进场检验制度，所有主要建筑材料和构配件均须具备出厂合格证和第三方检测报告，未经检验合格的材料一律不得用于工程施工。",
]

# ── 投标人 A 独有段落 ────────────────────────────────────────
BIDDER_A_UNIQUE = [
    "我公司成立于2005年，注册资金5000万元，具有建筑工程施工总承包一级资质。公司总部位于北京市朝阳区，在全国设有十二个分公司和办事处，员工总数超过两千人。",
    "近三年完成类似工程十余项，累计合同额超过8亿元，均获得业主和监理单位的一致好评。代表性项目包括某市体育中心综合楼和某高新区产业园基础设施工程等。",
    "本项目拟投入50名管理人员及200名技术工人，配备塔吊3台、混凝土泵车2台、挖掘机4台。施工高峰期日均混凝土浇筑量可达300立方米以上。",
    "质量目标为一次验收合格率100%，争创省级优质工程。我公司近五年获得省级以上工程质量奖项十六项，其中国家级优质工程奖两项。",
]

# ── 投标人 B 独有段落 ────────────────────────────────────────
BIDDER_B_UNIQUE = [
    "我公司创立于2008年，注册资本3000万元，拥有市政公用工程施工总承包一级资质。公司专注于市政基础设施建设领域，是本省市政工程行业协会理事单位。",
    "在过去五年中承接了多个大型市政基础设施项目，包括道路、桥梁、给排水和地下综合管廊等工程，具有丰富的施工管理经验和完善的质量保证体系。",
    "本项目计划安排45名专业管理人员和180名施工人员进场作业，其中高级技术工人占比不低于百分之三十五，确保各工序均由持证上岗的专业人员操作。",
    "我们将以精细化管理确保工程进度与质量的双重目标达成。项目实施采用PDCA循环管理模式，建立周报、月报和里程碑节点考核制度，确保工期受控。",
]

COMMON_AUTHOR = "张建国"
COMMON_COMPANY = "某建设集团有限公司"

BID_LETTER_TEXT = [
    "致：XX市公共资源交易中心",
    "根据贵方招标文件的要求，我公司经认真研究，愿意参加本项目的投标。",
    "我方投标总报价详见投标报价清单。",
    "我方承诺遵守招标文件的各项规定，保证投标文件的真实性。",
    "特此投标。",
]


def _build_zip(
    zip_path: Path,
    tech_paragraphs: list[str],
    author: str,
    price_row_count: int,
) -> None:
    TMP.mkdir(parents=True, exist_ok=True)

    # 技术方案.docx
    tech_docx = TMP / "技术方案.docx"
    make_real_docx(
        tech_docx,
        body_paragraphs=tech_paragraphs,
        header_text="XX项目技术方案",
        footer_text="机密文件",
        author=author,
    )

    # 投标函.docx
    bid_docx = TMP / "投标函.docx"
    make_real_docx(
        bid_docx,
        body_paragraphs=BID_LETTER_TEXT,
        author=author,
    )

    # 报价清单.xlsx
    price_xlsx = TMP / "报价清单.xlsx"
    make_price_xlsx(price_xlsx, row_count=price_row_count)

    # 打包 ZIP
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(tech_docx, "技术方案.docx")
        zf.write(bid_docx, "投标函.docx")
        zf.write(price_xlsx, "报价清单.xlsx")

    print(f"  -> {zip_path}  ({zip_path.stat().st_size:,} bytes)")


def main() -> None:
    print("生成 L3 E2E 测试 fixture ...")

    # bidder-a: 共享段落 + A 独有
    _build_zip(
        FIXTURE_DIR / "bidder-a.zip",
        tech_paragraphs=SHARED_PARAGRAPHS + BIDDER_A_UNIQUE,
        author=COMMON_AUTHOR,
        price_row_count=8,
    )

    # bidder-b: 共享段落 + B 独有（共享 6 段触发 text_similarity）
    _build_zip(
        FIXTURE_DIR / "bidder-b.zip",
        tech_paragraphs=SHARED_PARAGRAPHS + BIDDER_B_UNIQUE,
        author=COMMON_AUTHOR,
        price_row_count=8,
    )

    # 清理临时文件
    import shutil
    shutil.rmtree(TMP, ignore_errors=True)

    print("完成！")


if __name__ == "__main__":
    main()
