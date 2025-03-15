import struct
import time
import os
import re
# import json
from typing import Optional, cast
from pathlib import Path
from functools import lru_cache, cache
#from dataclasses import dataclass

from .common import *
from . import retroarch
from . import pil

os.chdir(Path(__file__).parent.parent)

def ud_thread():
    state = PadState()
    up = True
    while True:
        up = not up
        state.down = not up
        state.up = up
        retroarch.pad_send(state)
        time.sleep(0.2)

def debug_http():
    import logging
    logging.basicConfig(level=logging.DEBUG)
    import http.client
    http.client.HTTPConnection.debuglevel = 1 # 2
    # ^ can only go to stdout :(
#debug_http()
os.environ['SSLKEYLOGFILE'] = 'sslkeylogfile.txt'

# BUTTON_PRESS_FD = lambda: FunctionDeclaration(
#     name='button_press',
#     description='Press one or more buttons in the emulated game.  Buttons will be pressed sequentially for a duration of 1 second.  Instead of a button, you can also pass "wait" to just wait 1 second without pressing anything.',
#     parameters=Schema(
#         type=SType.OBJECT,
#         properties={
#             'buttons': Schema(
#                 type=SType.ARRAY,
#                 min_items=1,
#                 items=Schema(
#                     type=SType.STRING,
#                     format='enum',
#                     enum=['up', 'down', 'left', 'right', 'a', 'b', 'start', 'select', 'wait'],
#                 ),
#             ),
#         },
#         required=['buttons'],
#     ),

# )



INTRO_TEXT = '''
You are connected to an emulator playing a game of Pokémon Yellow Version.  You will receive screenshots of the current state, and you will be able to press buttons in response.  Your job is to beat the game.  Everything is up to you, from overall game strategy all the way down to individual button presses; you'll have to figure it out based on vision, reasoning, and any preexisting game knowledge.

While in the overworld, screenshots will be annotated with a grid.  Each grid square is overlaid with its coordinates prefixed by a letter.  The letter means:

- H means the square is the player's current position.
- X means the square is impassable.
- E means the square is passable *and* the entire path from the player's current position to that square is visible on-screen.
- P means the square is passable but the path from the current position to that square is either off-screen or nonexistent.

Example:
"E11,9" is the label for the grid square at (x=11, y=9) if it is passable and the path is visible on-screen.

After receiving each screenshot, you should respond in three parts.
- First, describe everything in the screenshot:
  - For each grid square with an identifiable object on it (NOT floor), briefly describe it and state its coordinates.  DO NOT list floor / ground / "empty space" squares or other repetitive squares.
  - For all game text on the screen (NOT coordinates from the overlay), recite the entire text.
- Then, explain your current thinking.
- Finally, you MUST end with a specially-formatted line starting with "ACTION:" followed by exactly one action in quotes.

The following actions are available (each button will be pressed for 0.5 seconds):
"a": press A
"b": press B
"up": press up on the D-pad
"left": press left on the D-pad
"down": press down on the D-pad
"right": press right on the D-pad
"select": press select
"start": press start

Examples:
ACTION: "a"
ACTION: "right"
'''
#"wait": press nothing, just wait 1 second

ADMONISH_TEXT = '''
Could not parse ACTION line out of that response.  Try again.  Make sure NOT to use JSON, except for quoting the individual actions as required.
For reference, here are your original instructions again:
''' + INTRO_TEXT

Action = str
def is_valid_action(a: object) -> bool:
    if isinstance(a, str):
        if a in BUTTONS:
            return True
        if a == 'wait':
            return False # !
    return False

def do_action(action: Action) -> None:
    if action in BUTTONS or action == 'wait':
        pad_state = PadState()
        if action != 'wait':
            setattr(pad_state, action, True)
        retroarch.pad_send(pad_state)
        print('Waiting 1 second...', flush=True, end='')
        time.sleep(1 if action == 'wait' else 0.25)
        print('done.')
        retroarch.pad_send(PadState())
        return
    raise Exception(f'!? {action!r}')

def parse_resp(resp: str) -> Optional[list[Action]]:
    resp = resp.replace('*', '') # sometimes it likes to bold things
    ms = re.findall(r'ACTIONS?"?:\s*"?([a-z]+)', resp, flags=re.I)
    if not ms:
        print(f'[No ACTION line: {resp!r}]')
        return None
    #actions = ms[-1]
    #try:
    #    parsed1 = json.loads(actions)
    #except json.decoder.JSONDecodeError:
    #    print(f'[JSON decode failed: {actions!r}]')
    #    return None
    #parsed: list[object]
    #if isinstance(parsed1, str):
    #    parsed = [parsed1]
    #elif isinstance(parsed1, list):
    #    parsed = parsed1
    #else:
    #    print(f'[Not a list: {parsed1!r}]')
    #    return None
    #if len(parsed) != 1:
    #    print(f'[Wrong number of actions: {parsed!r}]')
    #    return None
    parsed = [ms[-1]]
    for action in parsed:
        if not is_valid_action(action):
            print(f'[Invalid action: {action!r} in {parsed!r}]')
            return None
    return cast(list[Action], parsed)

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
        y, x = self.camera_pos()
        return x + 8, y + 9

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


def annotated_screenshot() -> Path:
    gs = GameSnapshot()
    return pil.annotate_screenshot(
        path=retroarch.screenshot(),
        camera_pos=gs.camera_pos(),
        reachable_state=reachable_state(gs),
        tile_map=gs.tile_map(),
        skip_tiles=bool(gs.in_battle()),
    )

def main():
    #do_chat()
    base_log_path: Optional[Path] = None # log_dir / 'log07.txt'
    from .ai import ChatWrap
    cw = ChatWrap(base_log_path)
    pre_prompt: Optional[str] = None # won't save, but whatever
    while True:
        if not cw.chat.get_history():
            text = INTRO_TEXT
            assert pre_prompt is None
        else:
            text = '\n'
            if pre_prompt is not None:
                text += pre_prompt
            text += 'Action accepted.  Current screenshot:'
        pre_prompt = None
        ss = annotated_screenshot()
        resp = cw.send(text, ss)
        bad_count = 0
        while (actions := parse_resp(resp)) is None:
            bad_count += 1
            #if bad_count >= 10:
            #    raise Exception('something is very wrong')
            admonish = ADMONISH_TEXT
            resp = cw.send(admonish, None)
        #if len(actions) > 3:
        #    need_actions_admonish = True
        #    actions = actions[:3]
        #    pre_prompt = f'Too many actions.  Using the first 3 ({json.dumps(actions)}) and ignoring the rest.'
        for action in actions:
            do_action(action)
        print('Waiting 1 more second for any responses...', flush=True, end='')
        time.sleep(1) # 
        print('done.')

if __name__ == '__main__':
    main()
    #print(GameSnapshot().camera_pos())
    #print(annotated_screenshot())
    #do_action('left')
