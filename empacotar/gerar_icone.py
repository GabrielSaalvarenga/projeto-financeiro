"""Gera empacotar/icone.png/.ico/.icns (rode de novo se quiser mudar o ícone). Precisa do Pillow."""
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent
S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
pad = 90  # margem padrão dos ícones do macOS
d.rounded_rectangle((pad, pad, S - pad, S - pad), radius=190, fill=(32, 110, 74))
d.rounded_rectangle((pad, pad, S - pad, S // 2), radius=190, fill=(43, 138, 62))
d.rectangle((pad, S // 2 - 190, S - pad, S // 2), fill=(43, 138, 62))
base, w, gap = 760, 120, 50
x0 = (S - (4 * w + 3 * gap)) // 2
for i, h in enumerate((200, 330, 260, 450)):
    x = x0 + i * (w + gap)
    d.rounded_rectangle((x, base - h, x + w, base), radius=28, fill=(255, 255, 255, 240))
d.rounded_rectangle((x0 - 30, base + 30, x0 + 4 * w + 3 * gap + 30, base + 62), radius=16, fill=(255, 255, 255, 180))
img.save(HERE / "icone.png")
img.save(HERE / "icone.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
img.save(HERE / "icone.icns")
print("ícones gerados em", HERE)
