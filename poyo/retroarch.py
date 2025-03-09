import socket
import time
import imageio.v3 as iio
import traceback
import struct
import re
from pathlib import Path
from typing import Iterable, Any, Optional, TYPE_CHECKING
import atexit

from .common import *


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
def shots() -> Iterable[Path]:
    return screenshot_dir.glob('Pokemon*.png')

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
                iio.imread(path) # type: ignore
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

@atexit.register
def clear_pad() -> None:
    print('clear_pad')
    pad_send(PadState())

def read_mem(addr: int, size: int, short_ok: bool = False) -> bytes:
    ret = None
    try:
        ret = rc_send_and_recv(f'READ_CORE_MEMORY {addr:x} {size}')
        m = re.fullmatch(r'READ_CORE_MEMORY ([^ ]+) (.*)\n', ret)
        assert m
        ret_addr, ret_bytes = m.groups()
        assert int(ret_addr, 16) == addr
        data = bytes.fromhex(ret_bytes)
        assert len(data) <= size
        if len(data) < size and not short_ok:
            raise ShortReadError
        return data
    except Exception as e:
        e.add_note(f'in read_mem({addr:#x}, {size}), ret={ret!r}')
        raise

#if __name__ == '__main__': main()
#def x():
#    #print(rc_send_and_recv(f'READ_CORE_MEMORY FF42 2'), rc_send_and_recv(f'READ_CORE_MEMORY FFAE 3'))
#    while True:
#        #print(rc_send_and_recv(f'READ_CORE_MEMORY C100 16'))
#        print(rc_send_and_recv(f'READ_CORE_MEMORY D360 2'))
#        time.sleep(0.2)
