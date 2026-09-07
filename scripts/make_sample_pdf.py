"""Generate a small Chinese sample manual PDF for end-to-end smoke tests.

Usage: python scripts/make_sample_pdf.py [output_path]
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz

PAGES = [
    [
        "XX 企业产品手册",
        "适用范围：本手册适用于 ZB-100 与 ZB-200 系列打印机。",
        "目录：第一章 保修政策；第二章 安装与配置；第三章 常见故障；第四章 维护与耗材。",
    ],
    [
        "第一章 保修政策",
        "ZB-100 打印机整机保修期为十二个月，自签收之日起计算。",
        "ZB-200 打印机整机保修期为二十四个月。",
        "保修期内因产品质量问题产生的维修费用由厂家承担；人为损坏不在保修范围内。",
    ],
    [
        "保修申请流程",
        "第一步：拨打服务热线 400-800-1234 报修。",
        "第二步：客服核对序列号与购买凭证。",
        "第三步：确认故障后安排上门维修或寄修。",
        "第四步：维修完成后由用户签字确认并保留维修工单。",
    ],
    [
        "第二章 安装与配置",
        "将打印机与电源连接，使用随机附带的 USB 线连接电脑。",
        "安装驱动前请先断开打印机电源，驱动安装完成后再开机。",
        "无线配置：长按面板 Wi-Fi 键 3 秒进入配对模式，在电脑端选择对应网络完成配置。",
    ],
    [
        "默认参数表",
        "型号 | 打印速度 | 纸盒容量 | 保修月数 | 网络接口",
        "ZB-100 | 30ppm | 250 张 | 12 | USB / 有线网络",
        "ZB-200 | 45ppm | 500 张 | 24 | USB / 有线 / 无线",
    ],
    [
        "第三章 常见故障排查",
        "故障现象：卡纸。处理方式：关闭电源，打开前盖，按箭头方向取出纸张。",
        "故障现象：指示灯红灯常亮。处理方式：检查纸盒是否缺纸或硒鼓是否安装到位。",
        "故障现象：无法打印。处理方式：检查驱动与连接线，重启打印机。",
    ],
    [
        "报错代码说明",
        "错误代码 E01 表示纸盒缺纸，补充纸张后按继续键。",
        "错误代码 E02 表示卡纸，参照第三章卡纸处理。",
        "错误代码 E05 表示墨粉不足，请更换对应型号硒鼓。",
    ],
    [
        "第四章 维护与耗材",
        "硒鼓型号：ZB-T100（适用于 ZB-100），打印量约 2000 页。",
        "硒鼓型号：ZB-T200（适用于 ZB-200），打印量约 5000 页。",
        "建议每三个月清洁一次进纸滚轮，长时间不使用请断电并遮盖防尘。",
    ],
    [
        "附录 服务网点",
        "北京、上海、广州、深圳、杭州设有官方服务中心。",
        "非服务网点区域支持寄修，运费由厂家承担（保修期内）。",
    ],
    [
        "附录 联系方式",
        "服务热线：400-800-1234（工作日 9:00-18:00）。",
        "官网：https://example.cn/support 可查询驱动与常见问题。",
    ],
]


def main() -> None:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "data/sample-manual.pdf")
    output.parent.mkdir(parents=True, exist_ok=True)

    font_candidates = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    font_path = next((candidate for candidate in font_candidates if Path(candidate).exists()), None)

    document = fitz.open()
    for index, lines in enumerate(PAGES, start=1):
        page = document.new_page()
        y = 72
        page.insert_text((72, y), f"第 {index} 页", fontsize=10)
        y += 24
        for line in lines:
            if font_path:
                page.insert_text((72, y), line, fontsize=12, fontname="noto", fontfile=font_path)
            else:
                page.insert_text((72, y), line.encode("ascii", errors="ignore").decode("ascii"), fontsize=12)
            y += 24
    document.save(output)
    document.close()
    print(f"sample PDF generated: {output}")


if __name__ == "__main__":
    main()
