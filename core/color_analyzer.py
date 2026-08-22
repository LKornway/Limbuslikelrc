"""
封面颜色分析模块。

从专辑封面提取主色和对比色，用于自动主题色功能。
采用 WCAG 对比度标准确保可读性。
"""

import colorsys
import math
from typing import Tuple, List, Optional
from PIL import Image


# ========== 色彩工具函数 ==========
def rgb_to_hsv(r: int, g: int, b: int) -> Tuple[float, float, float]:
    """RGB 转 HSV (h:0-1, s:0-1, v:0-1)"""
    return colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)


def hsv_to_rgb(h: float, s: float, v: float) -> Tuple[int, int, int]:
    """HSV 转 RGB (0-255)"""
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return int(r * 255), int(g * 255), int(b * 255)


def luminance(r: int, g: int, b: int) -> float:
    """计算相对亮度 (WCAG)"""
    def linearize(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b)


def contrast_ratio(r1, g1, b1, r2, g2, b2) -> float:
    """计算两种颜色的对比度 (WCAG)"""
    L1 = luminance(r1, g1, b1)
    L2 = luminance(r2, g2, b2)
    return (max(L1, L2) + 0.05) / (min(L1, L2) + 0.05)


def is_neutral(r: int, g: int, b: int,
               saturation_threshold: float = 0.15,
               value_threshold: float = 0.15,
               value_high: float = 0.85) -> bool:
    """判断是否为中性色（黑、白、灰）"""
    h, s, v = rgb_to_hsv(r, g, b)
    return s < saturation_threshold or v < value_threshold or v > value_high


def adjust_color_for_contrast(base_r, base_g, base_b, target_r, target_g, target_b,
                              min_ratio: float = 4.5) -> Tuple[int, int, int]:
    """
    调整目标颜色的明度，使其与基础颜色的对比度达到最低要求。
    优先调整明度，若不行则微调饱和度。
    """
    # 如果已经达到，直接返回
    if contrast_ratio(base_r, base_g, base_b, target_r, target_g, target_b) >= min_ratio:
        return target_r, target_g, target_b

    # 转换为 HSV
    h, s, v = rgb_to_hsv(target_r, target_g, target_b)

    # 尝试调整明度
    for v_candidate in [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1]:
        r_c, g_c, b_c = hsv_to_rgb(h, s, v_candidate)
        if contrast_ratio(base_r, base_g, base_b, r_c, g_c, b_c) >= min_ratio:
            return r_c, g_c, b_c

    # 如果调整明度失败，调整饱和度
    for s_candidate in [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1]:
        r_c, g_c, b_c = hsv_to_rgb(h, s_candidate, 0.9)
        if contrast_ratio(base_r, base_g, base_b, r_c, g_c, b_c) >= min_ratio:
            return r_c, g_c, b_c

    # 极端情况：返回黑白对比
    if luminance(base_r, base_g, base_b) > 0.5:
        return 0, 0, 0
    else:
        return 255, 255, 255


# ========== 主提取函数 ==========
def extract_dominant_colors(
    image: Image.Image,
    num_colors: int = 16,
    saturation_threshold: float = 0.15,
    value_threshold: float = 0.15,
    value_high: float = 0.85
) -> Tuple[Tuple[int, int, int], Optional[Tuple[int, int, int]]]:
    """
    提取主色和辅助色（非中性色中出现频率最高的两种）。

    Returns:
        (主色RGB, 辅助色RGB 或 None)
    """
    # 缩小以加速
    img = image.copy()
    img.thumbnail((100, 100))
    if img.mode != 'RGB':
        img = img.convert('RGB')

    # 量化
    img_quantized = img.quantize(colors=num_colors)
    palette = img_quantized.getpalette()

    # 提取颜色列表 (r,g,b,h,s,v)  —— 不再包含计数
    color_infos = []
    for i in range(num_colors):
        r = palette[i * 3]
        g = palette[i * 3 + 1]
        b = palette[i * 3 + 2]
        h, s, v = rgb_to_hsv(r, g, b)
        color_infos.append((r, g, b, h, s, v))

    # 统计每个颜色索引的像素数
    color_counts = {}
    for pixel in img_quantized.getdata():
        color_counts[pixel] = color_counts.get(pixel, 0) + 1

    # 过滤中性色，得到候选
    candidates = []
    for idx, count in color_counts.items():
        r, g, b, h, s, v = color_infos[idx]  # 现在解包6个值，没问题
        if not is_neutral(r, g, b, saturation_threshold, value_threshold, value_high):
            candidates.append((idx, count))

    if not candidates:
        # 全是中性色，回退到取出现最多的颜色作为主色，无辅助色
        best_idx = max(color_counts, key=color_counts.get)
        r, g, b, _, _, _ = color_infos[best_idx]
        return (r, g, b), None

    # 按频率排序
    candidates.sort(key=lambda x: x[1], reverse=True)

    # 主色
    main_idx = candidates[0][0]
    main_r, main_g, main_b, _, _, _ = color_infos[main_idx]
    main_color = (main_r, main_g, main_b)

    # 辅助色
    if len(candidates) > 1:
        sec_idx = candidates[1][0]
        sec_r, sec_g, sec_b, _, _, _ = color_infos[sec_idx]
        sec_color = (sec_r, sec_g, sec_b)
    else:
        sec_color = None

    return main_color, sec_color


def analyze_colors(image: Image.Image, min_contrast: float = 4.5) -> Tuple[Tuple[int, int, int], Tuple[int, int, int]]:
    """
    分析封面，返回主色和经过对比度调整的辅助色（用作文字颜色）。

    Args:
        image: PIL Image 对象
        min_contrast: 最小对比度要求 (WCAG)

    Returns:
        (主色RGB, 文字颜色RGB)
    """
    main_color, sec_color = extract_dominant_colors(image)

    # 如果没有辅助色，从主色生成互补色作为基础
    if sec_color is None:
        h, s, v = rgb_to_hsv(*main_color)
        h = (h + 0.5) % 1.0
        sec_color = hsv_to_rgb(h, 0.85, 0.9)

    # 调整辅助色以保证与主色的对比度
    adjusted_sec = adjust_color_for_contrast(
        *main_color, *sec_color, min_contrast
    )

    return main_color, adjusted_sec