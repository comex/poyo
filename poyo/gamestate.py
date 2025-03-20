import struct
import re
from pathlib import Path
from functools import lru_cache, cache
from typing import Optional, cast
from typing import Generic, Protocol, Iterable
from enum import IntEnum

from . import retroarch
from .common import *

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

class FacingDirection(IntEnum):
    RIGHT = 1
    LEFT = 2
    DOWN = 4
    UP = 8

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


class Symbols(dict[str, int]):
    @staticmethod
    @cache
    def instance() -> 'Symbols':
        return Symbols()
    def __init__(self):
        super().__init__()
        matches = re.findall(r'^\s*\$(....) = (\w[^ ]*)\s*$',
                             Path('data/pokeyellow.map').read_text(),
                             flags=re.M)
        for addr_str, name in matches:
            self[name] = int(addr_str, 16)


gsmemo = lru_cache(maxsize=4)
class GameSnapshot:
    def __init__(self):
        self.read_mem = retroarch.read_mem
        self.symbols = Symbols.instance()

    @gsmemo
    def camera_pos(self) -> Coord:
        y, x = self.read_mem(self.symbols['wYCoord'], 2)
        return x, y

    @gsmemo
    def tile_map(self) -> TileAccess[int]:
        raw = bytearray(self.read_mem(self.symbols['wTileMap'], SCREEN_WIDTH_TILES * SCREEN_HEIGHT_TILES))
        return TileAccess(raw)

    @gsmemo
    def collision_data(self) -> bytes:
        collision_ptr, = struct.unpack('<H', self.read_mem(self.symbols['wTilesetCollisionPtr'], 2))
        data = self.read_mem(collision_ptr, 256, short_ok=True)
        data = data[:data.index(b'\xff')]
        return data

    @gsmemo
    def passable_map(self) -> bytearray:
        ret = bytearray(256)
        for tile_id in self.collision_data():
            ret[tile_id] = 1
        return ret

    @gsmemo
    def player_pos(self) -> Coord: # not camera-relative
        x, y = self.camera_pos()
        return x + 4, y + 4

    @gsmemo
    def player_facing(self) -> FacingDirection:
        raw = self.read_mem(self.symbols['wPlayerDirection'], 1)[0]
        return FacingDirection(raw)

    @gsmemo
    def in_battle(self) -> int:
        return self.read_mem(self.symbols['wIsInBattle'], 1)[0]

# Based on LedgeTiles from pokered
ledge_tile_to_dir = {
    0x36: (0, 2),
    0x37: (0, 2),
    0x27: (-2, 0),
    0x0d: (2, 0),
    0x1d: (2, 0),
}
def can_visit(frum: Coord, to: Coord, passable_map: bytearray, tile_map: TileAccess[int]) -> Optional[TileState]:
    if not tile_loc_inbounds(*to):
        return None
    frum_tile, to_tile = tile_map[frum], tile_map[to]
    frum_ledge_dir = ledge_tile_to_dir.get(frum_tile)
    to_ledge_dir = ledge_tile_to_dir.get(to_tile)
    if ledge_dir := frum_ledge_dir or to_ledge_dir:
        if (
            to[0] == frum[0] + ledge_dir[0] and
            to[1] == frum[1] + ledge_dir[1]
        ):
            assert not (frum_ledge_dir and to_ledge_dir)
            if to_ledge_dir:
                if frum_tile in (0x2c, 0x39):
                    #print('can_visit: ok for ledge jump "step 1":', frum, to)
                    return TileState.LEDGE
                else:
                    print('can_visit: oddly no good for ledge jump "step 1":', frum, to, hex(frum_tile), hex(to_tile))
            else:
                if passable_map[to_tile]:
                    #print('can_visit: ok for ledge jump "step 2":', frum, to)
                    return TileState.REACHABLE
                else:
                    print('can_visit: oddly no good for ledge jump "step 2":', frum, to, hex(frum_tile), hex(to_tile))

        return None
    if passable_map[to_tile]:
        return TileState.REACHABLE
    return None

def reachable_state(gs: GameSnapshot) -> UsefulTileAccess[TileState]:
    tile_map = gs.tile_map()
    passable_map = gs.passable_map()

    ret: UsefulTileAccess[TileState] = UsefulTileAccess(
        cast(list[TileState], bytearray(SCREEN_WIDTH_TILES * SCREEN_HEIGHT_TILES)))
    for loc, tile_id in tile_map.items():
        if passable_map[tile_id] and ret.valid_xy(*loc):
            ret[loc] = TileState.PASSABLE

    player_loc = 8, 9
    ret[player_loc] = TileState.HERE

    # basic flood fill.
    todo: list[Coord] = [player_loc]
    while todo:
        xt, yt = frum = todo.pop()
        for to in [
            (xt - 2, yt),
            (xt + 2, yt),
            (xt, yt - 2),
            (xt, yt + 2),
        ]:
            new_state = can_visit(frum, to, passable_map, tile_map)
            if new_state is not None and new_state > ret[to]:
                ret[to] = new_state
                todo.append(to)

    return ret

def state_text(gs: GameSnapshot) -> str:
    bits: list[str] = []
    bits.append(f'Your position: {gs.player_pos()}')
    try:
        bits.append(f'Facing direction: {gs.player_facing().name}')
    except ValueError:
        logging.exception('welp')
    return '\n'.join(bits)

def main():
    logging.basicConfig(level=logging.DEBUG)
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['reachable-state', 'state-text'])
    args = ap.parse_args()
    gs = GameSnapshot()
    match args.mode:
        case 'reachable-state':
            for loc, state in reachable_state(gs).items():
                print(loc, TileState(state).name)
        case 'state-text':
            print(state_text(gs))
        case _:
            raise Exception('unreachable')

if __name__ == '__main__':
    main()
