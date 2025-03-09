import socket
import threading
import struct
import time
import atexit
import tempfile
import traceback
import datetime
import os
import re
import ast
import json
import traceback
from typing import Iterable, Any, Optional, TYPE_CHECKING
from pathlib import Path
from dataclasses import dataclass

os.chdir(Path(__file__).parent)

_a = time.time()
import google.genai # :( this is super slow
_b = time.time()
print('genai import time is', _b-_a)

from google.genai.types import PartUnionDict, Part, GenerateContentConfig, Tool, FunctionDeclaration, Schema, Type as SType, Content

import imageio.v3 as iio

rc_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
#sock.bind(('127.0.0.1', 0))
rc_sock.connect(('127.0.0.1', 55355))
pad_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
pad_sock.connect(('127.0.0.1', 55400))

def rc_send(cmd: str):
    rc_sock.sendall(cmd.encode('utf-8'))
def rc_send_and_recv(cmd: str) -> str:
    rc_send(cmd)
    return rc_sock.recv(65536).decode('utf-8')

screenshot_dir = Path('~/Documents/RetroArch/screenshots').expanduser()
log_dir = Path('~/Documents/poyo-log').expanduser()
log_dir.mkdir(exist_ok=True)
def shots() -> Iterable[Path]:
    return screenshot_dir.glob('Pokemon*.png')

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
next_screenshot_id = 1
def screenshot() -> Path:
    global next_screenshot_id
    for path in shots():
        path.unlink()
    pre = time.time()
    rc_send('SCREENSHOT')
    while True:
        s = list(shots())
        if s:
            if len(s) > 1:
                print('** multiple screenshots?', s)
            path = s[0]
            try:
                iio.imread(path)
            except:
                traceback.print_exc()
            else:
                break
        #print('...waiting for shot')
        time.sleep(0.05)
    post = time.time()
    print('got', path, 'after', post - pre)
    new_path, next_screenshot_id = get_unique_path(next_screenshot_id, log_dir, 'ss', 5, '.png')
    path.rename(new_path)
    return new_path

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
        return [name for name in PAD_STATE_ATTR_TO_RETRO_DEVICE_ID if getattr(self, name)]

# https://github.com/libretro/RetroArch/blob/master/libretro-common/include/libretro.h#L320
PAD_STATE_ATTR_TO_RETRO_DEVICE_ID = {
    'up': 4,
    'down': 5,
    'left': 6,
    'right': 7,
    'a': 8,
    'b': 9,
    'start': 3,
    'select': 2,
}

def pad_send(state: PadState):
    # https://github.com/libretro/RetroArch/blob/9cad6dd993c192030857733d8bd5f27616ece544/cores/libretro-net-retropad/net_retropad_core.c#L81
    print('pad_send:', state.as_list())
    msgs: list[bytes] = []
    for pad_state_attr, retro_device_id in PAD_STATE_ATTR_TO_RETRO_DEVICE_ID.items():
        val: bool = getattr(state, pad_state_attr)
        msgs.append(struct.pack('<IIIIHH',
            0, # port
            1, # device = RETRO_DEVICE_JOYPAD
            0, # index
            retro_device_id, # id
            int(val), # state
            0, # [padding]
        ))
    for msg in msgs:
        pad_sock.send(msg)

def ud_thread():
    state = PadState()
    up = True
    while True:
        up = not up
        state.down = not up
        state.up = up
        pad_send(state)
        time.sleep(0.2)

@atexit.register
def clear_pad():
    print('clear_pad')
    pad_send(PadState())

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

# why not just pickle it or something? because I want to be able to edit it if desired
def parse_log_bit(bit: str, ret: list[Content], parts: list[Part]) -> None:
    m = re.fullmatch(r'^20.*?  ([^:]*):(.*)', bit, flags=re.S)
    if not m:
        raise Exception('bad format 1')
    action, rest = m.groups()
    #print('^^', action)
    match action:
        case 'Sending':
            text = ast.literal_eval(rest)
            parts.append(Part.from_text(text=text))
        case 'Sending image':
            assert '/' not in rest
            image = log_dir / rest.strip()
            parts.append(Part.from_bytes(data=image.read_bytes(), mime_type='image/png'))
        case 'Response':
            resp = rest.replace('\n> ', '\n')
            assert resp.startswith('\n')
            resp = resp[1:]
            if not parts:
                raise Exception('No input for this response')
            ret.append(Content(role='user', parts=parts))
            parts.clear()
            ret.append(Content(role='model', parts=[Part.from_text(text=resp)]))
        case 'Loading log':
            m = re.fullmatch(r'^([^/]*) \(([0-9]+)\)$', rest.strip())
            assert m
            log_name, log_size = m.groups()
            ret.extend(parse_log(log_dir / log_name, int(log_size)))
        case _:
            raise Exception(f'Unknown action {action!r}')


def parse_log(path: Path, size: int) -> list[Content]:
    with open(path, 'rb') as fp:
        data = fp.read(size)
        assert len(data) == size
        text = data.decode('utf-8')
        bits = re.split(r'\n(?!>)', text)
        ret: list[Content] = []
        parts: list[Part] = []
        for bit in bits:
            bit = bit.strip()
            if not bit:
                continue
            try:
                parse_log_bit(bit, ret, parts)
            except:
                print('** while parsing bit:')
                print(bit)
                print('**')
                raise
        if parts:
            print('** Warning: Ignoring leftover send parts:', parts)
        return ret
next_log_id = 1
class ChatWrap:
    def __init__(self, base_log_path: Optional[Path] = None):
        global next_log_id
        gac = google.genai.Client(
            api_key=open('api_key.txt').read().strip(),
            http_options={'api_version':'v1alpha'}
        )
        # config = GenerateContentConfig(
        #     tools=[
        #         Tool(
        #             function_declarations=[
        #                 BUTTON_PRESS_FD(),
        #             ]
        #         )
        #     ]
        # )
        self.log_path, next_log_id = get_unique_path(next_log_id, log_dir, 'log', 2, '.txt')
        self.log_fp = self.log_path.open('w')
        print(f'Logging to {self.log_path}')
        if base_log_path is not None:
            history = self.load_log(base_log_path)
        else:
            history = []
        self.chat = gac.chats.create(
            model='gemini-2.0-flash-thinking-exp',
            # config=config
            history=history
        )
    def log(self, what: str, add_time: bool = True) -> None:
        if add_time:
            now = str(datetime.datetime.now())
            what = f'{now}  {what}'
        print(what, end='', flush=True)
        print(what, end='', flush=True, file=self.log_fp)
    def load_log(self, path: Path) -> list[Content]:
        size = path.stat().st_size
        self.log(f'Loading log: {path.name} ({size})\n')
        return parse_log(path, size)

    def send(self, text: str, image: Optional[Path] = None) -> str:
        self.log(f'Sending: {text!r}\n')
        if image:
            self.log(f'Sending image: {image.name}\n')
        parts: list[PartUnionDict] = [Part.from_text(text=text)]
        if image:
            parts.append(Part.from_bytes(data=image.read_bytes(), mime_type='image/png'))
        self.log(f'Response:\n> ')
        last_was_nl = False
        full_text = ''
        for chunk in self.chat.send_message_stream(parts):
            text = chunk.text or ''
            #print('?', chunk, repr(chunk.text))
            full_text += text
            if last_was_nl:
                text = '\n' + text
            last_was_nl = text.endswith('\n')
            if last_was_nl:
                text = text[:-1]
            self.log(text.replace('\n', '\n> '), add_time=False)
        self.log('\n', add_time=False)
        return full_text

INTRO_TEXT = '''
You are connected to an emulator playing a game of Pokémon Yellow Version.  You will receive screenshots of the current state, and you will be able to press buttons in response.  Your job is to beat the game.  Everything is up to you, from overall game strategy all the way down to individual button presses; you'll have to figure it out based on vision, reasoning, and any preexisting game knowledge.

After receiving each screenshot, you should respond in two parts.  First, explain your current thinking.  Then, you MUST end with a specially-formatted line starting with "ACTIONS:" followed by a JSON array of actions.  Each action is a string.

The following actions are available (each button will be pressed for 1 second):
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
ACTIONS: ["a"]
ACTIONS: ["right", "wait", "right", "right"]
'''

Action = str
def is_valid_action(a: Action) -> bool:
    if isinstance(a, str):
        if a in PAD_STATE_ATTR_TO_RETRO_DEVICE_ID:
            return True
        if a == 'wait':
            return True
    return False

def do_action(action: Action) -> None:
    if action in PAD_STATE_ATTR_TO_RETRO_DEVICE_ID or action == 'wait':
        pad_state = PadState()
        if action != 'wait':
            setattr(pad_state, action, True)
        pad_send(pad_state)
        print('Waiting 1 second...', flush=True, end='')
        time.sleep(1)
        print('done.')
        pad_send(PadState())
        return
    raise Exception(f'!? {action!r}')

def parse_resp(resp: str) -> Optional[list[Action]]:
    ms = re.findall('ACTIONS: (.*)', resp)
    if not ms:
        print('[No ACTIONS line: {resp!r}]')
        return None
    actions = ms[-1]
    try:
        parsed = json.loads(actions)
    except json.decoder.JSONDecodeError:
        print(f'[JSON decode failed: {actions!r}]')
        return None
    if not isinstance(parsed, list):
        print(f'[Not a list: {actions!r}]')
        return None
    for action in parsed:
        if not is_valid_action(action):
            print(f'[Not valid action: {action!r}]')
            return None
    return parsed

def main():
    #do_chat()
    base_log_path: Optional[Path] = None # log_dir / 'log07.txt'
    cw = ChatWrap(base_log_path)
    while True:
        if not cw.chat.get_history():
            text = INTRO_TEXT
        else:
            text = '\nCurrent screenshot:'
        ss = screenshot()
        resp = cw.send(text, ss)
        bad_count = 0
        while (actions := parse_resp(resp)) is None:
            bad_count += 1
            if bad_count >= 10:
                raise Exception('something is very wrong')
            admonish = '\nCould not parse ACTIONS line out of that response.  Try again.'
            resp = cw.send(admonish, None)
        for action in actions:
            do_action(action)
        print('Waiting 1 more second for any responses...', flush=True, end='')
        time.sleep(1) # 
        print('done.')

if __name__ == '__main__': main()
