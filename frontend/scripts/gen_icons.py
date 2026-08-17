"""生成 PWA 图标：圆角渐变底 + 白色 J 字 + 对勾（J人 = 计划型）。"""
from PIL import Image, ImageDraw, ImageFont

SIZES = [192, 512]
COLOR_TOP = (91, 124, 250)
COLOR_BOTTOM = (61, 90, 224)


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def rounded_gradient(size, radius_ratio=0.22):
    """圆角矩形 + 垂直渐变背景"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    r = int(size * radius_ratio)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=255)

    grad = Image.new("RGBA", (size, size))
    gdraw = ImageDraw.Draw(grad)
    for y in range(size):
        t = y / size
        gdraw.line([(0, y), (size, y)], fill=lerp(COLOR_TOP, COLOR_BOTTOM, t) + (255,))

    img.paste(grad, (0, 0), mask)
    return img, mask


def draw_letter(draw, size):
    """白色粗体 J（含下弧线），右上角小对勾"""
    # J 的主体：用线段+圆弧绘制，避免字体依赖
    x0, x1 = int(size * 0.32), int(size * 0.68)
    y0, y1 = int(size * 0.20), int(size * 0.62)
    lw = max(2, int(size * 0.10))
    # 竖线
    draw.rounded_rectangle([x0, y0, x0 + lw, y1], radius=lw // 2, fill=(255, 255, 255, 255))
    # 顶横
    draw.rounded_rectangle([x0 - lw // 2, y0, x1, y0 + lw], radius=lw // 2, fill=(255, 255, 255, 255))
    # 下弧线（J 的钩）
    cx, cy = x0 + lw // 2, y1
    for deg in range(0, 101):
        rad = 3.14159 * (1 + deg / 100)  # 180° -> 280°
        px = cx + (x1 - x0) * 0.5 * (1 + 0.55) * 0.5 * 1.0
        # 简化：用多段圆弧近似 —— 用三点画弧替代
    # 直接画钩：圆弧 + 底横
    arc_box = [x0 - int(size * 0.06), y1 - int(size * 0.20), x0 + int(size * 0.20), y1 + int(size * 0.02)]
    draw.arc(arc_box, start=0, end=180, fill=(255, 255, 255, 255), width=lw)
    draw.rounded_rectangle(
        [x0 - lw // 2, y1 - lw // 2, x0 + int(size * 0.14), y1 + lw // 2],
        radius=lw // 2, fill=(255, 255, 255, 255),
    )

    # 右上角小对勾
    gx0, gy0 = int(size * 0.72), int(size * 0.24)
    gw = int(size * 0.22)
    draw.line([(gx0, gy0 + gw * 0.55), (gx0 + gw * 0.4, gy0 + gw)], fill=(255, 255, 255, 255), width=lw)
    draw.line([(gx0 + gw * 0.4, gy0 + gw), (gx0 + gw, gy0 + gw * 0.1)], fill=(255, 255, 255, 255), width=lw)


def make_icon(size, path):
    img, mask = rounded_gradient(size)
    draw = ImageDraw.Draw(img)
    draw_letter(draw, size)
    img.save(path, "PNG")
    print(f"written {path}")


for s in SIZES:
    make_icon(s, f"icons/icon-{s}.png")

# SVG 版本（浏览器 favicon 用）
svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#5b7cfa"/>
      <stop offset="1" stop-color="#3d5ae0"/>
    </linearGradient>
  </defs>
  <rect x="0" y="0" width="512" height="512" rx="112" fill="url(#g)"/>
  <text x="256" y="330" font-family="Arial, Helvetica, sans-serif" font-size="240" font-weight="bold" fill="#ffffff" text-anchor="middle">J</text>
  <path d="M 370 110 l -30 90 l 60 -70" stroke="#ffffff" stroke-width="34" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
</svg>'''
with open("icons/icon.svg", "w", encoding="utf-8") as f:
    f.write(svg)
print("written icons/icon.svg")
