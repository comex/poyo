from pathlib import Path
from dataclasses import dataclass
from typing import Generic, Iterator, Protocol, TypeVar, Iterable, Callable
from enum import IntEnum
from contextlib import contextmanager
import io
import time
import faulthandler
import signal
import logging
import subprocess
import sys
import threading
from typing_extensions import Buffer

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

class Tail(io.RawIOBase):
    def __init__(self, filename: Path):
        filename.stat() # raise error if not accessible
        self.p = subprocess.Popen(
            [sys.executable, '-m', 'poyo.janitor', 'tail', '-n', '+1', '-f', '--', filename],
            bufsize=0,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )

    def read(self, size: int = -1, /) -> bytes:
        assert self.p.stdout is not None # for typing
        return self.p.stdout.read(size)

    def readinto(self, b: Buffer, /) -> int:
        assert self.p.stdout is not None # for typing
        return self.p.stdout.readinto(b) # type: ignore

    def readable(self):
        assert not self.closed
        return True

    def close(self) -> None:
        assert self.p.stdin is not None # for typing
        assert self.p.stdout is not None # for typing
        self.p.stdin.close()
        self.p.stdout.close()
        super().close()

def open_tail(filename: Path) -> io.TextIOWrapper:
    tail = Tail(filename)
    return io.TextIOWrapper(io.BufferedReader(tail))

def test_tail() -> None:
    path = Path('/tmp/test_tail.txt')
    ofp = open(path, 'wb', buffering=0)
    ifp = open_tail(path)
    ofp.write(b'asdf')
    assert ifp.read(1) == 'a'
    ofp.write(b'\n')
    assert ifp.readline() == 'sdf\n'
    c = None
    def thread() -> None:
        nonlocal c
        c = ifp.read(1)
    t = threading.Thread(target=thread)
    t.start()
    time.sleep(1)
    assert c is None
    pre = time.time()
    ofp.write(b'x')
    t.join()
    post = time.time()
    assert c == 'x'
    assert post - pre < 0.1


def _main() -> None:
    test_tail()

if __name__ == '__main__': _main()
