from pathlib import Path
from .common import *

SCALE_FACTOR = 6
def annotate_screenshot(path: Path, reachable_state: UsefulTileAccess[TileState]) -> Path:
    out_path = path.with_suffix('.annotated.png')
    from PIL import Image, ImageDraw
    with Image.open(path) as image:
        #import time
        #a = time.time()
        ow, oh = image.size
        assert (ow, oh) == (160, 144)
        big = image.resize((ow*6, oh*6))#, resample=Image.Resampling.NEAREST)
        draw = ImageDraw.Draw(big, 'RGBA')
        for xst in range(SCREEN_WIDTH_SUPERTILES):
            for yst in range(SCREEN_HEIGHT_SUPERTILES):
                x_off = xst * SUPERTILE_WIDTH_PX * SCALE_FACTOR
                y_off = yst * SUPERTILE_HEIGHT_PX * SCALE_FACTOR
                text = f'({xst} ,{yst})' # this spacing looks a bit better when rendered
                font_size = 16

                xt = xst * 2
                yt = yst * 2 + 1
                state = reachable_state[xt, yt]

                if passable_by_supertile_loc[yst * SCREN_WIDTH_SUPERTILES + xst]:
                    bg_color = '#00000080'
                    fg_color = '#00ff80'
                else:
                    bg_color = '#00000080'
                    fg_color = '#ff0000'


                # ew, why do we need to render twice (to get bbox and then for real)
                bbox = draw.textbbox((x_off, y_off), text, font_size=font_size)
                draw.rectangle(bbox, fill=bg_color)
                draw.text((x_off, y_off), text, fill=fg_color, font_size=font_size)
        big.save(out_path)
        #b = time.time()
        #print(b-a)
    return out_path



