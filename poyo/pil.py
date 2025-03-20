from pathlib import Path
from .common import *
from .gamestate import TileState, UsefulTileAccess, TileAccess, SCREEN_WIDTH_TILES, SCREEN_HEIGHT_TILES, TILE_WIDTH_PX, TILE_HEIGHT_PX


STATE_TO_COLOR = {
    TileState.IMPASSABLE: ('#000000', '#ff0000'),
    TileState.PASSABLE:   ('#0000ff', '#000000'),
    TileState.REACHABLE:  ('#00ff80', '#000000'),
    TileState.LEDGE:      ('#00ff80', '#000000'),
    # ^ for now, don't tell the model what ledges are
    TileState.HERE:       ('#ffffff', '#000000'),
}
STATE_TO_PREFIX = {
    TileState.IMPASSABLE: 'X',
    TileState.PASSABLE:   'P',
    TileState.REACHABLE:  'E',
    TileState.LEDGE:      'E',
    TileState.HERE:       'H',
}
SCALE_FACTOR = 4
JUST_DRAW_TILES = False
def annotate_screenshot(path: Path, camera_pos: Coord, reachable_state: UsefulTileAccess[TileState], tile_map: TileAccess[int], skip_tiles: bool) -> Path:
    out_path = path.with_suffix('.annotated.png')
    from PIL import Image, ImageDraw
    with Image.open(path) as image:
        #import time
        #a = time.time()
        ow, oh = image.size
        assert (ow, oh) == (160, 144)
        big = image.resize(
            (ow * SCALE_FACTOR, oh * SCALE_FACTOR),
            #resample=Image.Resampling.NEAREST,
        )
        draw = ImageDraw.Draw(big, 'RGBA')

        font_size = 16
        anchor = 'mm'
        stroke_width = 1

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
                    tile_tl_x = xt * TILE_WIDTH_PX * SCALE_FACTOR
                    tile_tl_y = yt * TILE_HEIGHT_PX * SCALE_FACTOR
                    text = f'{xt},{yt}=\n${tile_map[xt,yt]:x}'
                    fg_color = 'white' if is_map else 'red'
                    #stroke_color = 'black'
                    draw_text = True
                else:
                    if not is_map:
                        continue

                    tile_tl_x = xt * TILE_WIDTH_PX * SCALE_FACTOR
                    tile_tl_y = (yt - 1) * TILE_HEIGHT_PX * SCALE_FACTOR
                    xpos, ypos = camera_pos[0] + xt // 2, camera_pos[1] + yt // 2

                    state = reachable_state[xt, yt]
                    #fg_color, stroke_color = STATE_TO_COLOR[state]
                    fg_color = 'white'

                    draw_text = True

                    pfx = STATE_TO_PREFIX[state]
                    text = f'{pfx}{xpos},{ypos}'
                if draw_text:
                    text_anchor_x = tile_tl_x + (TILE_WIDTH_PX * SCALE_FACTOR * 2 // 2)
                    text_anchor_y = tile_tl_y + (TILE_HEIGHT_PX * SCALE_FACTOR * 2 // 2)
                    # ew, why do we need to render twice (to get bbox and then for real)
                    bb_x1, bb_y1, bb_x2, bb_y2 = draw.textbbox(
                        (text_anchor_x, text_anchor_y),
                        text,
                        anchor=anchor,
                        font_size=font_size,
                        stroke_width=stroke_width,
                    )
                    # pad
                    bb_x1 -= 2; bb_y1 -= 2; bb_x2 += 2; bb_y2 += 0
                    # Shift so that text is exactly hitting the top left corner:
                    # (no longer now that it's centered)
                    x_adjust = 0 # tile_tl_x - bb_x1
                    y_adjust = 0 # tile_tl_y - bb_y1

                    # text background
                    if 1:
                        bg_color = '#00000080'
                        draw.rectangle((bb_x1 + x_adjust, bb_y1 + y_adjust,
                                        bb_x2 + x_adjust, bb_y2 + y_adjust),
                                       fill=bg_color)
                    draw.text(
                        (text_anchor_x + x_adjust, text_anchor_y + y_adjust),
                        text,
                        anchor=anchor,
                        fill=fg_color,
                        font_size=font_size,
                        #stroke_width=stroke_width,
                        #stroke_fill=stroke_color,
                    )

                # grid rect
                draw.rectangle((tile_tl_x,
                                tile_tl_y,
                                tile_tl_x + 2 * TILE_WIDTH_PX * SCALE_FACTOR,
                                tile_tl_y + 2 * TILE_WIDTH_PX * SCALE_FACTOR),
                               outline='black')
        big.save(out_path)
        #b = time.time()
        #print(b-a)
    return out_path



