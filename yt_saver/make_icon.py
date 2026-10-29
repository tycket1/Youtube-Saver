"""Draws the YT Saver icon (original artwork) and writes icon.ico + icon.png."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

S = 1024                      # draw big, scale down for smooth edges
here = Path(__file__).parent


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def make(size=S):
    top, bottom = (20, 184, 166), (79, 70, 229)      # teal -> indigo
    grad = Image.new("RGB", (size, size))
    px = grad.load()
    for y in range(size):
        for x in range(size):
            t = min(1.0, max(0.0, (x * 0.35 + y * 0.65) / size))
            px[x, y] = lerp(top, bottom, t)

    # rounded-square tile with a soft drop shadow
    m = int(size * 0.06)
    r = int(size * 0.22)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([m, m, size - m, size - m], r, fill=255)

    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sm = Image.new("L", (size, size), 0)
    ImageDraw.Draw(sm).rounded_rectangle([m, m + size * 0.02, size - m, size - m + size * 0.02], r, fill=90)
    shadow.putalpha(sm.filter(ImageFilter.GaussianBlur(size * 0.02)))

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    img.alpha_composite(shadow)
    tile = grad.convert("RGBA")
    tile.putalpha(mask)
    img.alpha_composite(tile)

    # gentle top highlight
    hl = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    hm = Image.new("L", (size, size), 0)
    ImageDraw.Draw(hm).ellipse([-size * 0.3, -size * 0.75, size * 1.3, size * 0.42], fill=46)
    hm = hm.filter(ImageFilter.GaussianBlur(size * 0.06))
    hm = Image.composite(hm, Image.new("L", (size, size), 0), mask)
    hl.putalpha(hm)
    img.alpha_composite(hl)

    # white download arrow into a tray
    d = ImageDraw.Draw(img)
    w = (255, 255, 255, 255)
    cx = size / 2
    stem_w = size * 0.115
    d.rounded_rectangle([cx - stem_w / 2, size * 0.22, cx + stem_w / 2, size * 0.56], stem_w / 2, fill=w)
    head = size * 0.22
    d.polygon([(cx - head, size * 0.43), (cx + head, size * 0.43), (cx, size * 0.66)], fill=w)
    tray_w, tray_t = size * 0.27, size * 0.075
    y0, y1 = size * 0.66, size * 0.79
    d.rounded_rectangle([cx - tray_w - tray_t / 2, y0, cx - tray_w + tray_t / 2, y1], tray_t / 2, fill=w)
    d.rounded_rectangle([cx + tray_w - tray_t / 2, y0, cx + tray_w + tray_t / 2, y1], tray_t / 2, fill=w)
    d.rounded_rectangle([cx - tray_w - tray_t / 2, y1 - tray_t, cx + tray_w + tray_t / 2, y1], tray_t / 2, fill=w)
    return img


if __name__ == "__main__":
    big = make()
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    big.resize((256, 256), Image.LANCZOS).save(here / "icon.png")
    big.resize((512, 512), Image.LANCZOS).save(here / "icon_512.png")
    big.save(here / "icon.ico", sizes=[(s, s) for s in sizes])
    print("wrote icon.ico, icon.png")
