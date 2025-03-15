from pathlib import Path
from dataclasses import dataclass
from typing import Generic, Iterator, Protocol, TypeVar, Iterable, Callable
from enum import IntEnum
from contextlib import contextmanager
import time
import faulthandler
import signal
import logging

T = TypeVar('T')

Coord = tuple[int, int]

faulthandler.register(signal.SIGUSR1)
if hasattr(signal, 'SIGINFO'):
    faulthandler.register(signal.SIGINFO)

log_dir = (Path(__file__).parent / '../log').resolve()

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

class TileState(IntEnum):
    IMPASSABLE = 0
    PASSABLE = 1
    REACHABLE = 2
    LEDGE = 3
    HERE = 4

def tile_loc_inbounds(x: int, y: int) -> bool:
    return (
        0 <= x < SCREEN_WIDTH_TILES and
        0 <= y < SCREEN_HEIGHT_TILES
    )

class IntGetSet(Protocol[T]):
    def __setitem__(self, index: int, value: T, /) -> None: ...
    def __getitem__(self, index: int, /) -> T: ...

class TileAccess(Generic[T]):
    def __init__(self, igs: IntGetSet[T]) -> None:
        self.igs = igs
    def __getitem__(self, key: Coord) -> T:
        return self.igs[self.key2index(key)]
    def __setitem__(self, key: Coord, value: T) -> None:
        self.igs[self.key2index(key)] = value
    def key2index(self, key: Coord) -> int:
        x, y = key
        assert tile_loc_inbounds(x, y), (x, y)
        assert self.valid_xy(x, y)
        return y * SCREEN_WIDTH_TILES + x
    def valid_xy(self, x: int, y: int) -> bool:
        return True
    def items(self) -> Iterable[tuple[Coord, T]]:
        for y in range(SCREEN_HEIGHT_TILES):
            for x in range(SCREEN_WIDTH_TILES):
                if self.valid_xy(x, y):
                    tup = x, y
                    yield (tup, self[tup])

class UsefulTileAccess(Generic[T], TileAccess[T]):
    def valid_xy(self, x: int, y: int) -> bool:
        return x % 2 == 0 and y % 2 == 1

def xtime(f: Callable[[], T]) -> T:
    a = time.time()
    ret = f()
    b = time.time()
    print('xtime:', b - a)
    return ret

@contextmanager
def operation(desc: str) -> Iterator[None]:
    logging.info(f'{desc}: start')
    a = time.time()
    yield
    b = time.time()
    logging.info(f'{desc}: finished after {1000 * (b - a):.0f}ms')
