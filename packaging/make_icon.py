from pathlib import Path

from PIL import Image, ImageDraw

size = 256
image = Image.new("RGBA", (size, size), "#2463a0")
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=52, fill="#2463a0")
draw.polygon([(68, 38), (154, 38), (198, 82), (198, 218), (68, 218)], fill="white")
draw.polygon([(154, 38), (154, 84), (198, 84)], fill="#bcd8ee")
for y, width in [(118, 76), (144, 76), (170, 54)]:
    draw.rounded_rectangle((94, y, 94 + width, y + 12), radius=6, fill="#2463a0")
output = Path(__file__).with_name("clearview.ico")
image.save(output, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)])
print(output)
