"""Draw the FacebookDiary icon: a closed blue diary with a ribbon and a small clock (Pillow)."""
import os
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "icons")
os.makedirs(OUT, exist_ok=True)


def draw(n=1024):
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    s = n / 1024
    R = lambda *v: [x * s for x in v]
    d.rounded_rectangle(R(250, 120, 830, 900), radius=40 * s, fill=(236, 230, 214))          # pages
    for i in range(6):
        y = 150 + i * 120
        d.line(R(800, y, 800, y + 80), fill=(200, 192, 172), width=int(6 * s))
    d.rounded_rectangle(R(190, 100, 780, 920), radius=48 * s, fill=(38, 84, 150))             # cover
    d.rounded_rectangle(R(190, 100, 290, 920), radius=48 * s, fill=(27, 60, 112))             # spine
    d.rectangle(R(250, 100, 290, 920), fill=(27, 60, 112))
    d.rounded_rectangle(R(360, 230, 700, 380), radius=18 * s, fill=(244, 240, 228))           # label
    for i, w in enumerate((260, 200)):
        d.rounded_rectangle(R(400, 270 + i * 50, 400 + w, 290 + i * 50), radius=8 * s, fill=(120, 130, 150))
    d.polygon(R(600, 900, 600, 1000, 640, 965, 680, 1000, 680, 900), fill=(205, 60, 60))     # ribbon
    cx, cy, r = 530, 640, 165                                                                  # clock
    d.ellipse(R(cx - r - 18, cy - r - 18, cx + r + 18, cy + r + 18), fill=(244, 240, 228))
    d.ellipse(R(cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255), outline=(27, 60, 112), width=int(14 * s))
    import math
    for k in range(12):
        a = k * math.pi / 6
        r1, r2 = (r - 40, r - 14) if k % 3 == 0 else (r - 28, r - 14)
        d.line(R(cx + r1 * math.sin(a), cy - r1 * math.cos(a), cx + r2 * math.sin(a), cy - r2 * math.cos(a)),
               fill=(27, 60, 112), width=int(10 * s))
    d.line(R(cx, cy, cx, cy - 110), fill=(27, 60, 112), width=int(20 * s))
    d.line(R(cx, cy, cx + 80, cy + 40), fill=(205, 60, 60), width=int(18 * s))
    d.ellipse(R(cx - 18, cy - 18, cx + 18, cy + 18), fill=(27, 60, 112))
    return im


big = draw()
for size in (16, 24, 32, 48, 64, 128, 256, 512):
    big.resize((size, size), Image.LANCZOS).save(os.path.join(OUT, f"facebookdiary-{size}.png"))
big.resize((256, 256), Image.LANCZOS).save(            # Windows (Start-menu shortcut)
    os.path.join(OUT, "facebookdiary.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
big.resize((1024, 1024), Image.LANCZOS).save(os.path.join(OUT, "facebookdiary.icns"))   # macOS app bundle
print("icons written to", OUT)
