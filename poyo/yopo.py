import os
os.environ['SSLKEYLOGFILE'] = 'sslkeylogfile.txt'

import time
import re
# import json
from typing import Optional, Any
from pathlib import Path
#from dataclasses import dataclass

from .common import *
from .log import Content, ImageContent, Message, MessageList, MessageTags, StatelessWrapper, TextContent
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

ENABLE_NEW_OR_CHANGED = False

INTRO_TEXT = '''
You are connected to an emulator playing a game of Pokémon Yellow Version.  You will receive screenshots of the current state, and you will be able to press buttons in response.  Your job is to beat the game.  Everything is up to you, from overall game strategy all the way down to individual button presses; you'll have to figure it out based on vision, reasoning, and any preexisting game knowledge.

While in the overworld, screenshots will be annotated with a grid.  Each grid square is overlaid with its coordinates.  Squares which are blocked/impassable have coordinates in *orange*; squares which are walkable have coordinates in *white*.

The coordinate origin is top left; higher Y coordinates are lower on the screen.

After receiving each screenshot, you should respond in two parts.
- First, describe everything [NC:NEW or CHANGED ]in the screenshot:
  - For each grid square with an identifiable object on it (NOT floor)[NC: which is newly visible or changed], briefly describe it and state its coordinates.
  - For all [NC:new or changed ]game text on the screen (NOT coordinates from the overlay), recite the entire text.
- Then, explain your current thinking and goals.
- Finally, you MUST end with a specially-formatted line starting with "ACTION:" followed by exactly one action.

The following actions are available (each button will be pressed for 0.5 seconds):
- ACTION: a
- ACTION: b
- ACTION: up
- ACTION: left
- ACTION: down
- ACTION: right
- ACTION: select
- ACTION: start

Tips:
- Don't assume the exit is in a specific direction.  Explore the whole area.
- The game is NOT broken.  The screen is not frozen.  If you think you can't move in a direction, it might mean:
  - There is a text box or other UI element taking input.
  - You're up against a wall
  - You're getting confused in some other way
Do not give up!  Instead, revisit your assumptions.

- Do not hallucinate.  Are you sure the screen shows what you think it does?
- Only write in English.
'''
#"wait": press nothing, just wait 1 second

INTRO_TEXT = re.sub(r'\[NC:(.*?)\]', lambda m: m[1] if ENABLE_NEW_OR_CHANGED else '', INTRO_TEXT) # type: ignore

NO_ACTION_TEXT = '''
Could not parse ACTION line out of that response.  Try again.
'''

CHECKUP1_TEXT = f'''
Time for a periodic checkup.

Summarize your progress and list the positions you've been to since the last time you saw instructions.

List any important lessons that you've learned.

Then think about what your overall goals should be to continue the game.
'''

CHECKUP2_TEXT = f'''
Okay, now it's time to continue the game.

Just for reference, here are your instructions again.
{INTRO_TEXT}
'''

LIST_ALL_TEXT = '''
This is a special turn: you should list everything in the screenshot, not just new or changed things.  Next time you should go back to listing new or changed things.
'''

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
        logging.info(f'Waiting {wait_time}s before releasing...')
        time.sleep(wait_time)
        logging.info(f'Releasing and waiting another 1s...')
        retroarch.pad_send(PadState())
        time.sleep(1)
        logging.info('Done waiting.')
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

def state_machine(ml: MessageList) -> tuple[Message, MessageTags]:
    text_bits: list[str] = []
    tags: MessageTags = []
    need_shot = False

    if not ml:
        text_bits.append(INTRO_TEXT)
        tags.append('instructions')
        need_shot = True
    else:
        last_send_idx = ml.last_message_idx_with_tag('send')
        assert last_send_idx is not None, 'recv without send?'
        last_send_tags = ml[last_send_idx].tags

        # even on checkup1 I guess we can try to parse
        assert 'recv' in ml[-1].tags
        action = parse_resp(ml[-1].all_text_content())
        if action is not None:
            do_action(action)
            text_bits.append(f'Action {action} accepted.')
            tags.append('accept')
        elif 'checkup1' not in last_send_tags:
            text_bits.append(NO_ACTION_TEXT)
            tags.append('no_action')


        last_instructions_idx = ml.last_message_idx_with_tag('instructions')
        assert last_instructions_idx is not None, 'we never sent instructions?'

        last_accept_idx = ml.last_message_idx_with_tag('accept')
        if last_accept_idx is None: last_accept_idx = -1

        if 'checkup1' in last_send_tags:
            text_bits.append(CHECKUP2_TEXT)
            tags += ['checkup2', 'instructions']
            need_shot = True

        elif len(ml) - last_instructions_idx >= 60 or len(ml) - last_accept_idx >= 20:
            # This intentionally can be combined with no_action.
            text_bits.append(CHECKUP1_TEXT)
            tags.append('checkup1')
        else:
            need_shot = True

        if ENABLE_NEW_OR_CHANGED:
            last_listall_idx = ml.last_message_idx_with_tag('list_all')
            if (
                need_shot and
                'checkup1' not in tags and
                'instructions' not in tags and
               ( last_listall_idx is None or len(ml) - last_listall_idx >= 20)
            ):
                text_bits.append(LIST_ALL_TEXT)
                tags.append('list_all')

    assert tags, "we didn't figure out what to do?"

    content: list[Content] = []

    if need_shot:
        gs = GameSnapshot()
        text_bits.append('Current state:\n' + state_text(gs))
        tags.append('state')
        ss = annotated_screenshot(gs)
        content.append(ImageContent.from_name(ss.name))
        tags.append('screenshot')

    all_text = '\n\n'.join(map(str.strip, text_bits))
    content.insert(0, TextContent(all_text))
    m = Message(role='user', content=content)
    return m, tags


def trim_to_token_limit(wrap: StatelessWrapper) -> None:
    n = 0
    while wrap.message_list.total_tokens > wrap.token_limit:
        # Can we just remove the first message?
        if wrap.message_list.last_message_idx_with_tag('instructions') != 0:
            wrap.remove_message(0)
            n += 1
            continue
        if len(wrap.message_list) <= 2:
            raise Exception("we sent instructions that were way too long?")
        wrap.remove_message(1)
        n += 1
    logging.info(f'Trimmed {n} messages, {len(wrap.message_list)} left ({wrap.message_list.total_tokens} tokens)')


def remove_images(wrap: StatelessWrapper, max_images: int) -> None:
    remaining = max_images
    for i, m in reversed(list(enumerate(wrap.message_list))):
        if any(isinstance(c, ImageContent) for c in m.content):
            if remaining > 0:
                remaining -= 1
                continue
            wrap.redact_images_from_message(i)

def remove_trailing_sends(wrap: StatelessWrapper) -> None:
    # If the list somehow ends in a send then drop it.
    last_recv = wrap.message_list.last_message_idx_with_tag('recv')
    while last_recv is not None and last_recv != len(wrap.message_list) - 1:
        wrap.remove_message(-1)


def main_ai(args: Any):
    #do_chat()
    log_path: Optional[Path] = args.log_path
    if log_path is None:
        log_path, _ = get_unique_path(0, log_dir, 'log', 2, '.txt')
    print(log_path)
    wrap = StatelessWrapper(OpenAISession(), log_path)

    while True:
        remove_trailing_sends(wrap)
        remove_images(wrap, max_images=0)
        trim_to_token_limit(wrap)
        m, tags = state_machine(wrap.message_list)
        wrap.send(m, tags, recv_limit=20000)

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
