import socket
import threading
import struct
import time
import atexit
import tempfile
import traceback
from typing import Iterable
from pathlib import Path
from dataclasses import dataclass


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
temp_screenshot_dir = screenshot_dir.parent / 'poyo_tmp'
temp_screenshot_dir.mkdir(exist_ok=True)
def shots() -> Iterable[Path]:
    return screenshot_dir.glob('Pokemon*.png')
def screenshot() -> tempfile.NamedTemporaryFile:
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
    #print('got', path, 'after', post - pre)
    tf = tempfile.NamedTemporaryFile(dir=temp_screenshot_dir)
    path.rename(tf.name)
    return tf

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

def main():
    threading.Thread(target=ud_thread).start()
    while True:
        print(screenshot())
        time.sleep(1)
        
    pass
if __name__ == '__main__': main()
