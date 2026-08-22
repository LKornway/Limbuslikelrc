"""
封面颜色分析模块。

从专辑封面提取主色和对比色，用于自动主题色功能。
"""

import colorsys
from typing import Tuple, Optional
from PIL import Image


def extract_dominant_color(
    image: Image.Image,
    num_colors: int = 16,
    saturation_threshold: float = 0.15,
    value_threshold: float = 0.15,
    value_high: float = 0.85
) -> Tuple[int, int, int]:
    """
    提取图片主色，过滤中性色。

    Args:
        image: PIL Image 对象。
        num_colors: 量化颜色数。
        saturation_threshold: 饱和度阈值（低于此值视为灰色）。
        value_threshold: 明度下限（低于此值视为黑色）。
        value_high: 明度上限（高于此值视为白色）。

    Returns:
        (r, g, b) 主色元组。
    """
    # 缩小以加速
    img = image.copy()
    img.thumbnail((100, 100))
    if img.mode != 'RGB':
        img = img.convert('RGB')

    # 量化减少颜色
    img_quantized = img.quantize(colors=num_colors)
    palette = img_quantized.getpalette()
    colors = []
    for i in range(num_colors):
        r = palette[i * 3]
        g = palette[i * 3 + 1]
        b = palette[i * 3 + 2]
        h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        colors.append((r, g, b, h, s, v))

    # 统计每个颜色索引的像素数
    color_counts = {}
    for pixel in img_quantized.getdata():
        color_counts[pixel] = color_counts.get(pixel, 0) + 1

    # 过滤中性色
    candidates = []
    for idx, count in color_counts.items():
        _, _, _, h, s, v = colors[idx]
        if s < saturation_threshold or v < value_threshold or v > value_high:
            continue
        candidates.append((idx, count))

    if candidates:
        candidates.sort(key=lambda x: x[1], reverse=True)
        best_idx = candidates[0][0]
        r, g, b, _, _, _ = colors[best_idx]
        return (r, g, b)
    else:
        # 回退：取出现最多的颜色
        best_idx = max(color_counts, key=color_counts.get)
        r, g, b, _, _, _ = colors[best_idx]
        return (r, g, b)


def get_contrasting_color(r: int, g: int, b: int) -> Tuple[int, int, int]:
    """
    生成互补对比色。

    Args:
        r, g, b: 主色 RGB。

    Returns:
        (r, g, b) 对比色元组。
    """
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    # 互补色
    h_c = (h + 0.5) % 1.0
    # 调整饱和度和明度以保证视觉舒适
    s_c = 0.85
    v_c = 0.9 if v < 0.7 else 0.8
    r_c, g_c, b_c = colorsys.hsv_to_rgb(h_c, s_c, v_c)
    return int(r_c * 255), int(g_c * 255), int(b_c * 255)


def analyze_colors(image: Image.Image) -> Tuple[Tuple[int, int, int], Tuple[int, int, int]]:
    """
    分析图片，返回主色和对比色。

    Args:
        image: PIL Image 对象。

    Returns:
        (主色RGB, 对比色RGB)
    """
    dominant = extract_dominant_color(image)
    contrast = get_contrasting_color(*dominant)
    return dominant, contrast