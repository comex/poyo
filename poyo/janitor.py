'''
Spawn a process (which must not use stdin), but read stdin ourselves and die if
stdin is closed.
'''
assert __name__ == '__main__'

import sys
import subprocess
import os
import threading
import signal
import time

os.setsid()

def kill_me():
    os.killpg(os.getpgrp(), signal.SIGTERM)
    time.sleep(10)
    sys.stderr.write(f'poyo.janitor: kill_me did not\n')
    sys.stderr.flush()

def stdin_thread():
    data = os.read(0, 1)
    if data:
        # we expect the pipe to never be used for anything but closing
        sys.stderr.write(f'poyo.janitor: stdin read returned nonempty: {data!r}\n')
        sys.stderr.flush()
    kill_me()

threading.Thread(target=stdin_thread, daemon=True).start()

p = subprocess.Popen(
    sys.argv[1:],
    stdin=subprocess.DEVNULL,
)

p.wait()
kill_me()
