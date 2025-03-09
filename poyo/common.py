from pathlib import Path
from dataclasses import dataclass
log_dir = Path('~/Documents/poyo-log').expanduser()

def get_unique_path(next_id: int, dir: Path, prefix: str, precision: int, suffix: str) -> tuple[Path, int]:
    while True:
        new_path = dir / f'{prefix}{next_id:0{precision}}{suffix}'
        try:
            f = new_path.open('xb')
        except FileExistsError:
            next_id += 1
        else:
            break
    f.close()
    return new_path, next_id
log_dir.mkdir(exist_ok=True)

BUTTONS = ['up', 'down', 'left', 'right', 'a', 'b', 'start', 'select']
@dataclass
class PadState:
    up: bool = False
    down: bool = False
    left: bool = False
    right: bool = False
    a: bool = False
    b: bool = False
    start: bool = False
    select: bool = False

    def as_list(self) -> list[str]:
        return [name for name in BUTTONS if getattr(self, name)]

class ShortReadError(Exception):
    pass

def assert_int(x: float) -> int:
    assert int(x) == x, x
    return int(x)

SCREEN_WIDTH_TILES = 20
SCREEN_HEIGHT_TILES = 18
TILE_WIDTH_PX = 8
TILE_HEIGHT_PX = 8

SUPERTILE_WIDTH_TILES = 1
SUPERTILE_HEIGHT_TILES = 1

SCREEN_WIDTH_SUPERTILES = assert_int(SCREEN_WIDTH_TILES / SUPERTILE_WIDTH_TILES)
SCREEN_HEIGHT_SUPERTILES = assert_int(SCREEN_HEIGHT_TILES / SUPERTILE_HEIGHT_TILES)
SUPERTILE_WIDTH_PX = TILE_WIDTH_PX * SUPERTILE_WIDTH_TILES
SUPERTILE_HEIGHT_PX = TILE_HEIGHT_PX * SUPERTILE_HEIGHT_TILES

