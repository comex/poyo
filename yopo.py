import socket
import threading
import struct
import time
import atexit
import tempfile
import traceback
import datetime
import os
from typing import Iterable, Any, Optional, TYPE_CHECKING
from pathlib import Path
from dataclasses import dataclass

os.chdir(Path(__file__).parent)

_a = time.time()
import google.genai # :( this is super slow
_b = time.time()
print('genai import time is', _b-_a)

from google.genai.types import PartUnionDict, Part, GenerateContentConfig, Tool, FunctionDeclaration, Schema, Type as SType

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

BUTTON_PRESS_FD = lambda: FunctionDeclaration(
    name='button_press',
    description='Press one or more buttons in the emulated game.  Buttons will be pressed sequentially for a duration of 1 second.  Instead of a button, you can also pass "wait" to just wait 1 second without pressing anything.',
    parameters=Schema(
        type=SType.OBJECT,
        properties={
            'buttons': Schema(
                type=SType.ARRAY,
                min_items=1,
                items=Schema(
                    type=SType.STRING,
                    format='enum',
                    enum=['up', 'down', 'left', 'right', 'a', 'b', 'start', 'select', 'wait'],
                ),
            ),
        },
        required=['buttons'],
    ),

)
next_log_id = 1
class ChatWrap:
    def __init__(self):
        global next_log_id
        gac = google.genai.Client(
            api_key=open('api_key.txt').read().strip(),
            http_options={'api_version':'v1alpha'}
        )
        config = GenerateContentConfig(
            tools=[
                Tool(
                    function_declarations=[
                        BUTTON_PRESS_FD(),
                    ]
                )
            ]
        )
        self.chat = gac.chats.create(
            model='gemini-2.0-flash-thinking-exp',
            config=config
        )
        self.log_path, next_log_id = get_unique_path(next_log_id, log_dir, 'log', 2, '.txt')
        self.log_fp = self.log_path.open('w')
        print(f'Logging to {self.log_path}')
    def log(self, what: str, add_time: bool = True) -> None:
        if add_time:
            now = str(datetime.datetime.now())
            what = f'{now}  {what}'
        print(what, end='', flush=True)
        print(what, end='', flush=True, file=self.log_fp)
    def send(self, text: str, image: Optional[Path] = None) -> None:
        self.log(f'Sending: {text!r}\n')
        if image:
            self.log(f'Sending image: {image.name}\n')
        parts: list[PartUnionDict] = [Part.from_text(text=text)]
        if image:
            parts.append(Part.from_bytes(data=image.read_bytes(), mime_type='image/png'))
        self.log(f'Response:\n> ')
        last_was_nl = False
        for chunk in self.chat.send_message_stream(parts):
            print('**', text)
            text = chunk.text
            if last_was_nl:
                text = '\n' + text
            last_was_nl = text.endswith('\n')
            if last_was_nl:
                text = text[:-1]
            self.log(text.replace('\n', '\n> '), add_time=False)
        self.log('\n', add_time=False)

INTRO_TEXT = '''
You are connected to an emulator playing a game of Pokémon Yellow Version.  You will receive screenshots of the game as images, and you can control the game using the button_press function call.  Your job is to beat the game.
'''

def main():
    #do_chat()
    cw = ChatWrap()
    cw.send(INTRO_TEXT)
    ss = screenshot()
    cw.send('Current screenshot:', image=ss)
if __name__ == '__main__': main()
