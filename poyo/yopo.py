import struct
import time
import os
import re
import json
from typing import Optional, cast, TypeVar, Callable
from copy import copy
from pathlib import Path
from functools import lru_cache, cache
#from dataclasses import dataclass

from .common import *
from . import retroarch
from . import pil

os.chdir(Path(__file__).parent)

def ud_thread():
    state = PadState()
    up = True
    while True:
        up = not up
        state.down = not up
        state.up = up
        retroarch.pad_send(state)
        time.sleep(0.2)

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

After receiving each screenshot, you should respond in three parts.
- First, describe what you see in the screenshot:
  - For each visible object, briefly describe it and (if it's an overworld object) where it is relative to the player.
    - Then double-check that the object is still on the screen!
  - For all text on the screen, recite the entire text.
- Then, explain your current thinking.
- Finally, you MUST end with a specially-formatted line starting with "ACTION:" followed by exactly one action as a JSON-quoted string.

The following actions are available (each button will be pressed for 0.5 seconds):
"a": press A
"b": press B
"up": press up on the D-pad
"left": press left on the D-pad
"down": press down on the D-pad
"right": press right on the D-pad
"select": press select
"start": press start
"wait": press nothing, just wait 1 second

Examples:
ACTION: "a"
ACTION: "right"

There is a limit of 3 actions per response.  To perform any more actions you must wait for the next screenshot.
'''

Action = str
def is_valid_action(a: object) -> bool:
    if isinstance(a, str):
        if a in BUTTONS:
            return True
        if a == 'wait':
            return True
    return False

def do_action(action: Action) -> None:
    if action in BUTTONS or action == 'wait':
        pad_state = PadState()
        if action != 'wait':
            setattr(pad_state, action, True)
        retroarch.pad_send(pad_state)
        print('Waiting 1 second...', flush=True, end='')
        time.sleep(1 if action == 'wait' else 0.5)
        print('done.')
        retroarch.pad_send(PadState())
        return
    raise Exception(f'!? {action!r}')

def parse_resp(resp: str) -> Optional[list[Action]]:
    ms = re.findall(r'ACTIONS?: (.*)', resp)
    if not ms:
        print(f'[No ACTIONS line: {resp!r}]')
        return None
    actions = ms[-1]
    try:
        parsed1 = json.loads(actions)
    except json.decoder.JSONDecodeError:
        print(f'[JSON decode failed: {actions!r}]')
        return None
    parsed: list[object]
    if isinstance(parsed1, str):
        parsed = [parsed1]
    elif isinstance(parsed1, list):
        parsed = parsed1
    else:
        print(f'[Not a list: {parsed1!r}]')
        return None
    if len(parsed) != 1:
        print(f'[Wrong number of actions: {parsed!r}]')
        return None
    for action in parsed:
        if not is_valid_action(action):
            print(f'[Invalid action: {action!r} in {parsed!r}]')
            return None
    return cast(list[Action], parsed)

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
            text += 'Current screenshot:'
        pre_prompt = None
        ss = retroarch.screenshot()
        resp = cw.send(text, ss)
        bad_count = 0
        while (actions := parse_resp(resp)) is None:
            bad_count += 1
            if bad_count >= 10:
                raise Exception('something is very wrong')
            admonish = '\nCould not parse ACTIONS line out of that response.  Try again.'
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

class Symbols(dict[str, int]):
    @staticmethod
    @cache
    def instance() -> 'Symbols':
        return Symbols()
    def __init__(self):
        super().__init__()
        matches = re.findall(r'^\s*\$(....) = (\w[^ ]*)\s*$',
                             Path('../data/pokeyellow.map').read_text(),
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
        x, y = self.read_mem(self.symbols['wYCoord'], 2)
        return x, y

    @gsmemo
    def tile_map(self) -> bytearray:
        return bytearray(self.read_mem(self.symbols['wTileMap'], SCREEN_WIDTH_TILES * SCREEN_HEIGHT_TILES))

    @gsmemo
    def collision_data(self) -> bytes:
        collision_ptr, = struct.unpack('<H', self.read_mem(self.symbols['wTilesetCollisionPtr'], 2))
        data = self.read_mem(collision_ptr, 256, short_ok=True)
        data = data[:data.index(b'\xff')]
        return data

    @gsmemo
    def passable_by_tile_loc(self) -> TileAccess[int]:
        passable_by_id = bytearray(256)
        passable_by_loc = bytearray(SCREEN_WIDTH_TILES * SCREEN_HEIGHT_TILES)
        for tile in self.collision_data():
            passable_by_id[tile] = 1
        for loc, tile_id in enumerate(self.tile_map()):
            passable_by_loc[loc] = passable_by_id[tile_id]
        return TileAccess(passable_by_loc)

    @gsmemo
    def player_pos(self) -> Coord: # not camera-relative
        y, x = self.camera_pos()
        return x + 8, y + 9

    @gsmemo
    def in_battle(self) -> int:
        return self.read_mem(self.symbols['wIsInBattle'], 1)[0]

def can_visit(frum: Coord, to: Coord, passable: TileAccess[int]) -> bool:
    if not tile_loc_inbounds(*to):
        return False
    if passable[to]:
        return True
    return False

def reachable_state(gs: GameSnapshot) -> UsefulTileAccess[TileState]:
    passable = gs.passable_by_tile_loc()

    raw = copy(passable.igs)
    ret: UsefulTileAccess[TileState] = UsefulTileAccess(cast(list[TileState], raw))

    player_loc = 8, 9
    ret[player_loc] = TileState.HERE

    REACHABLE = TileState.REACHABLE

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
            if can_visit(frum, to, passable) and ret[to] < REACHABLE:
                ret[to] = REACHABLE
                todo.append(to)

    return ret


def xtime(f: Callable[[], T]) -> T:
    a = time.time()
    ret = f()
    b = time.time()
    print('xtime:', b - a)
    return ret


gs = GameSnapshot()
#print('TB:', gs.read_mem(gs.symbols['wTextBoxID'], 1)[0])
print(pil.annotate_screenshot(
    path=retroarch.screenshot(),
    camera_pos=gs.camera_pos(),
    reachable_state=reachable_state(gs),
    tile_map=TileAccess(gs.tile_map()),
    skip_tiles=bool(gs.in_battle()),
))
#if __name__ == '__main__': main()
