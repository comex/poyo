import socket
import threading
import struct
import time
import tempfile
import traceback
import datetime
import os
import re
import json
import traceback
from typing import Iterable, Any, Optional, TYPE_CHECKING
from pathlib import Path
from dataclasses import dataclass

from poyo.common import *
from poyo import retroarch
from poyo.retroarch import read_mem

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
def is_valid_action(a: Action) -> bool:
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
        parsed = json.loads(actions)
    except json.decoder.JSONDecodeError:
        print(f'[JSON decode failed: {actions!r}]')
        return None
    if isinstance(parsed, str):
        parsed = [parsed]
    if not isinstance(parsed, list):
        print(f'[Not a list: {parsed!r}]')
        return None
    if len(parsed) != 1:
        print(f'[Wrong number of actions: {parsed!r}]')
        return None
    for action in parsed:
        if not is_valid_action(action):
            print(f'[Invalid action: {action!r} in {parsed!r}]')
            return None
    return parsed

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


read_mem(0xd360, 2)
#if __name__ == '__main__': main()
