from pathlib import Path
from functools import cache
from typing import TYPE_CHECKING, TypeAlias
import time
if TYPE_CHECKING:
    from PIL import ImageFont

SCREEN_WIDTH_SUPERTILES = 10
SCREEN_HEIGHT_SUPERTILES = 9
SUPERTILE_WIDTH_PX = 16
SUPERTILE_HEIGHT_PX = 16

XFont: TypeAlias = 'ImageFont.ImageFont | ImageFont.FreeTypeFont'
@cache
def font() -> XFont:
    from PIL import ImageFont
    return ImageFont.load_default()

SCALE_FACTOR = 6
def annotate_screenshot(path: Path) -> Path:
    out_path = path.with_suffix('.annotated.png')
    from PIL import Image, ImageDraw
    with Image.open(path) as image:
        ow, oh = image.size
        assert (ow, oh) == (160, 144)
        big = image.resize((ow*6, oh*6))
        draw = ImageDraw.Draw(big)
        for xst in range(SCREEN_WIDTH_SUPERTILES):
            for yst in range(SCREEN_HEIGHT_SUPERTILES):
                x_off = xst * SUPERTILE_WIDTH_PX * SCALE_FACTOR
                y_off = yst * SUPERTILE_HEIGHT_PX * SCALE_FACTOR
                draw.text((x_off, y_off), f'({xst},{yst})')
        big.save(out_path)
    return out_path



