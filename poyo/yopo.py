import os
os.environ['SSLKEYLOGFILE'] = 'sslkeylogfile.txt'

import time
import re
# import json
from typing import Optional, Any
from pathlib import Path
#from dataclasses import dataclass

from .common import *
from .log import ImageContent, Message, StatelessWrapper, TextContent
from .openai import OpenAISession
from .gamestate import GameSnapshot, reachable_state, state_text
from . import retroarch
from . import pil

os.chdir(Path(__file__).parent.parent)
log_dir.mkdir(exist_ok=True)

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
        wait_time = 0.25
        logging.info(f'Waiting {wait_time}s...')
        time.sleep(wait_time)
        logging.info('Done waiting.')
        retroarch.pad_send(PadState())
        return
    raise Exception(f'!? {action!r}')

def parse_resp(resp: str) -> Optional[Action]:
    resp = resp.replace('*', '') # sometimes it likes to bold things
    ms = re.findall(r'ACTIONS?"?:\s*"?([a-z]+)', resp, flags=re.I)
    if not ms:
        logging.warning(f'[No ACTION line: {resp!r}]')
        return None
    action = ms[-1]
    if not is_valid_action(action):
        logging.warning(f'[Invalid action: {action!r}]')
        return None
    return action

def annotated_screenshot(gs: GameSnapshot) -> Path:
    return pil.annotate_screenshot(
        path=retroarch.screenshot(),
        camera_pos=gs.camera_pos(),
        reachable_state=reachable_state(gs),
        tile_map=gs.tile_map(),
        skip_tiles=bool(gs.in_battle()),
    )

def main_ai(args: Any):
    #do_chat()
    log_path: Optional[Path] = args.log_path
    if log_path is None:
        log_path, _ = get_unique_path(0, log_dir, 'log', 2, '.txt')
    print(log_path)
    wrap = StatelessWrapper(OpenAISession(), log_path)

    last_action = None
    while True:
        gs = GameSnapshot()
        if not wrap.message_list:
            text = INTRO_TEXT
        elif last_action is not None:
            text = 'Action {last_action} accepted.\n'
        else:
            text = ''
        text += 'Current state:\n'
        text += state_text(gs)
        ss = annotated_screenshot(gs)
        resp: str = wrap.send(Message(role='user', content=[
            TextContent(text=text),
            ImageContent.from_name(ss.name),
        ]))
        bad_count = 0
        while (action := parse_resp(resp)) is None:
            bad_count += 1
            if bad_count >= 10:
                raise Exception('something is very wrong')
            admonish = ADMONISH_TEXT
            resp = wrap.send(Message(role='user', content=[
                TextContent(text=admonish),
            ]))

        do_action(action)
        last_action = action

        logging.info('Waiting 1 more second for game...')
        time.sleep(1)
        logging.info('done.')

def main_screenshot(args: Any):
    if args.annotated:
        path = annotated_screenshot(GameSnapshot())
    else:
        path = retroarch.screenshot()
    print(path)

def main():
    import argparse
    ap = argparse.ArgumentParser()
    subparsers = ap.add_subparsers(required=True)
    xap = subparsers.add_parser('ai')
    xap.add_argument('log_path', nargs='?', type=Path)
    xap.set_defaults(func=main_ai)
    xap = subparsers.add_parser('screenshot')
    xap.add_argument('-a', '--annotated', action='store_true')
    xap.set_defaults(func=main_screenshot)
    args = ap.parse_args()
    args.func(args)

if __name__ == '__main__':
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s %(levelname)-8s %(message)s',
    )
    main()
    #print(GameSnapshot().camera_pos())
    #print(annotated_screenshot())
    #do_action('left')
