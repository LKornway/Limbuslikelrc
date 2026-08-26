"""
封面颜色分析模块。

从专辑封面提取主色和辅助色，用于自动主题色功能。
采用 WCAG 对比度标准确保可读性。

策略：
1. 把封面缩略图量化为少量颜色并统计占比，再合并 RGB 距离很近的近似色，
   得到「封面主要颜色及占比」清单（不预先排除黑白灰等中性色）；
2. 主色 = 占比最大的颜色；辅助色 = 按占比顺序寻找第一个与主色
   对比度达标（默认 4.5）的封面原生颜色；
3. 仅当封面原生颜色确实无法满足对比度时，才对辅助色做最小幅度的
   明度调整（保持色相），不再激进压暗/去饱和，也不再凭空生成互补色；
4. 可读性修正：若主色（用作描边）接近黑色而文字色偏浅，则互换两者，
   避免浅色字幕在亮色背景下难以辨认。
"""

import colorsys
import math

from typing import Tuple, Optional
from PIL import Image

# 近似色合并阈值（RGB 欧氏距离）
MERGE_THRESHOLD = 24.0
# 参与对比度配对扫描的颜色数量上限（按占比降序取前 N 个）
PAIR_CANDIDATES = 8
# 缩略图尺寸上限
THUMBNAIL_SIZE = (96, 96)
# 量化颜色数
QUANTIZE_COLORS = 24
# 可读性修正阈值：主色（描边）相对亮度低于该值视为接近黑色；
# 此时若文字色相对亮度高于该值（偏浅），说明浅色字幕难以辨认，
# 将主色与文字色互换。
DARK_STROKE_LUMINANCE = 0.1
LIGHT_TEXT_LUMINANCE = 0.5


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


def _color_distance(c1, c2) -> float:
    """RGB 欧氏距离。"""
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(c1, c2)))


def _extract_color_clusters(
    image: Image.Image,
    num_colors: int = QUANTIZE_COLORS,
    merge_threshold: float = MERGE_THRESHOLD,
) -> list:
    """
    量化封面并统计各颜色占比，合并近似色。

    Returns:
        list[dict]: 按占比降序，每项为
        {"color": (r,g,b), "count": int, "proportion": float}
    """
    img = image.copy()
    img.thumbnail(THUMBNAIL_SIZE)
    if img.mode != "RGB":
        img = img.convert("RGB")

    quantized = img.quantize(colors=num_colors)
    palette = quantized.getpalette()

    counts: dict[int, int] = {}
    for pixel in quantized.tobytes():
        counts[pixel] = counts.get(pixel, 0) + 1

    items = [
        (palette[i * 3], palette[i * 3 + 1], palette[i * 3 + 2], cnt)
        for i, cnt in counts.items()
    ]
    items.sort(key=lambda t: t[3], reverse=True)

    clusters = []
    for r, g, b, cnt in items:
        color = (r, g, b)
        target = None
        for cluster in clusters:
            if _color_distance(color, cluster["color"]) <= merge_threshold:
                target = cluster
                break
        if target is None:
            clusters.append({"color": color, "count": cnt})
        else:
            total = target["count"] + cnt
            target["color"] = tuple(
                round((target["color"][k] * target["count"] + color[k] * cnt) / total)
                for k in range(3)
            )
            target["count"] = total

    total_pixels = sum(c["count"] for c in clusters)
    for cluster in clusters:
        cluster["proportion"] = (
            cluster["count"] / total_pixels if total_pixels else 0.0
        )

    clusters.sort(key=lambda c: c["proportion"], reverse=True)
    return clusters


def _pick_contrasting_pair(clusters, min_contrast: float, top_n: int = PAIR_CANDIDATES):
    """
    从占比清单中选择主色与辅助色。

    主色 = 占比最大的颜色；
    辅助色 = 按占比顺序找到的第一个与主色对比度达标（min_contrast）的颜色；
    若前 top_n 个都未达标，则退而选择占比第二大的颜色
    （仍为封面原生颜色，后续由 analyze_colors 做最小幅度调整）。

    Returns:
        (main_cluster, sec_cluster 或 None)
    """
    if not clusters:
        return None, None

    main = clusters[0]
    sec = None

    for cluster in clusters[1:top_n]:
        if contrast_ratio(*main["color"], *cluster["color"]) >= min_contrast:
            sec = cluster
            break

    if sec is None and len(clusters) > 1:
        sec = clusters[1]

    return main, sec


def _minimal_adjust_for_contrast(base, target, min_ratio: float):
    """
    在保持色相/饱和度的前提下，以最小明度步进调整目标色，
    使其与基础色的对比度达到 min_ratio。

    明度每次只调整 0.05（从最小幅度开始，首次命中即返回），
    最多调整 0.85；仍不达标才退回纯黑/纯白（取对比度更高者）。
    """
    if contrast_ratio(*base, *target) >= min_ratio:
        return target

    h, s, v = rgb_to_hsv(*target)
    base_lum = luminance(*base)

    for step in range(1, 18):
        delta = step * 0.05
        for v_candidate in (min(1.0, v + delta), max(0.0, v - delta)):
            if v_candidate == v:
                continue
            candidate = hsv_to_rgb(h, s, v_candidate)
            if contrast_ratio(*base, *candidate) >= min_ratio:
                return candidate

    black_ratio = contrast_ratio(*base, 0, 0, 0)
    white_ratio = contrast_ratio(*base, 255, 255, 255)
    return (0, 0, 0) if black_ratio >= white_ratio else (255, 255, 255)


def extract_dominant_colors(
    image: Image.Image,
    num_colors: int = QUANTIZE_COLORS,
    min_contrast: float = 4.5,
) -> Tuple[Tuple[int, int, int], Optional[Tuple[int, int, int]]]:
    """
    提取主色和辅助色（封面中占比最大的两种颜色，且尽量满足对比度要求）。

    返回的颜色均直接来自封面（不做调整）；仅在封面颜色无法满足
    对比度要求时，辅助色退回占比第二大的封面原生颜色。

    Args:
        image: PIL Image 对象。
        num_colors: 量化颜色数。
        min_contrast: 主/辅色间的最低对比度要求（WCAG）。

    Returns:
        (主色RGB, 辅助色RGB 或 None)
    """
    clusters = _extract_color_clusters(image, num_colors=num_colors)
    main, sec = _pick_contrasting_pair(clusters, min_contrast)
    return (main["color"] if main else None), (sec["color"] if sec else None)


def analyze_colors(
    image: Image.Image,
    min_contrast: float = 4.5,
) -> Tuple[Tuple[int, int, int], Tuple[int, int, int]]:
    """
    分析封面，返回主色和用作文字颜色的辅助色。

    优先直接使用封面原生颜色对；仅当封面颜色确实无法满足对比度时，
    才对辅助色做最小幅度的明度调整（保持色相）。单色封面时，
    从主色按明度翻转生成同色相辅助色。
    主色接近黑色而文字色偏浅时，互换两者以保证字幕可读性。

    Args:
        image: PIL Image 对象
        min_contrast: 最小对比度要求 (WCAG)

    Returns:
        (主色RGB, 文字颜色RGB)
    """
    main_color, sec_color = extract_dominant_colors(image, min_contrast=min_contrast)

    if main_color is None:
        return (255, 255, 255), (0, 0, 0)

    # 单色封面：没有第二个颜色，用同色相、明度翻转的颜色作辅助色
    if sec_color is None:
        h, s, v = rgb_to_hsv(*main_color)
        sec_color = hsv_to_rgb(h, s, 0.95 if v < 0.5 else 0.05)

    adjusted_sec = _minimal_adjust_for_contrast(main_color, sec_color, min_contrast)

    # 可读性修正：主色（用作描边）接近黑色而文字色偏浅时互换两者，
    # 避免浅色字幕在亮色背景下难以辨认。对比度与两色顺序无关，互换后不变。
    if (
        luminance(*main_color) < DARK_STROKE_LUMINANCE
        and luminance(*adjusted_sec) > LIGHT_TEXT_LUMINANCE
    ):
        main_color, adjusted_sec = adjusted_sec, main_color

    return main_color, adjusted_sec
