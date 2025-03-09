from pathlib import Path
from .common import *


STATE_TO_COLOR = {
    TileState.IMPASSABLE: ('#00000080', '#ff0000'),
    TileState.PASSABLE:   ('#00000080', '#0000ff'),
    TileState.REACHABLE:  ('#00000080', '#00ff80'),
    TileState.LEDGE:      ('#00000080', '#00ff80'), # '#ff00ff'),
    # ^ for now, don't tell the model what ledges are
    TileState.HERE:       ('#00000080', '#ffffff'),
}
SCALE_FACTOR = 6
JUST_DRAW_TILES = False
def annotate_screenshot(path: Path, camera_pos: Coord, reachable_state: UsefulTileAccess[TileState], tile_map: TileAccess[int], skip_tiles: bool) -> Path:
    out_path = path.with_suffix('.annotated.png')
    from PIL import Image, ImageDraw
    with Image.open(path) as image:
        #import time
        #a = time.time()
        ow, oh = image.size
        assert (ow, oh) == (160, 144)
        big = image.resize((ow*6, oh*6))#, resample=Image.Resampling.NEAREST)
        draw = ImageDraw.Draw(big, 'RGBA')
        font_size = 16
        step = 1 if JUST_DRAW_TILES else 2
        xt_min, yt_min = 0, 1
        xt_max, yt_max = SCREEN_WIDTH_TILES, SCREEN_HEIGHT_TILES
        if JUST_DRAW_TILES:
            yt_min = 0
        elif skip_tiles:
            yt_max = 0

        for xt in range(xt_min, xt_max, step):
            for yt in range(yt_min, yt_max, step):
                tile = tile_map[xt, yt]
                is_map = tile <= 0x5f
                if JUST_DRAW_TILES:
                    x_off = xt * TILE_WIDTH_PX * SCALE_FACTOR
                    y_off = yt * TILE_HEIGHT_PX * SCALE_FACTOR
                    text = f'{xt},{yt}=\n${tile_map[xt,yt]:x}'
                    bg_color = '#00000080'
                    fg_color = 'white' if is_map else 'red'
                    draw_text = True
                else:
                    if not is_map:
                        continue

                    x_off = xt * TILE_WIDTH_PX * SCALE_FACTOR
                    y_off = (yt - 1) * TILE_HEIGHT_PX * SCALE_FACTOR
                    xpos, ypos = camera_pos[0] + xt // 2, camera_pos[1] + yt // 2
                    text = f'({xpos} ,{ypos})' # this spacing looks a bit better when rendered

                    state = reachable_state[xt, yt]
                    bg_color, fg_color = STATE_TO_COLOR[state]

                    draw_text = True
                if draw_text:
                    # ew, why do we need to render twice (to get bbox and then for real)
                    bb_x1, bb_y1, bb_x2, bb_y2 = draw.textbbox((x_off, y_off), text, font_size=font_size)
                    # pad
                    bb_x1 -= 2; bb_y1 -= 2; bb_x2 += 2; bb_y2 += 0
                    # Shift so that text is exactly hitting the top left corner:
                    x_adjust = x_off - bb_x1
                    y_adjust = y_off - bb_y1
                    
                    # text background
                    draw.rectangle((bb_x1 + x_adjust, bb_y1 + y_adjust,
                                    bb_x2 + x_adjust, bb_y2 + y_adjust),
                                   fill=bg_color)
                    draw.text((x_off + x_adjust, y_off + y_adjust),
                              text,
                              fill=fg_color,
                              font_size=font_size)

                # grid rect
                draw.rectangle((x_off,
                                y_off,
                                x_off + 2 * TILE_WIDTH_PX * SCALE_FACTOR,
                                y_off + 2 * TILE_WIDTH_PX * SCALE_FACTOR),
                               outline='black')
        big.save(out_path)
        #b = time.time()
        #print(b-a)
    return out_path



