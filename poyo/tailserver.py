from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Optional
import subprocess
import re
import time
import select

from poyo.common import Tail

# (started as) lowest effort possible
class MyHTTPRequestHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if not (m := re.search(r'\?(tail|slow)$', self.path)):
            return super().do_GET()
        mode = m[1]
        path = Path(self.translate_path(self.path))
        assert path.exists()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        print('...')
        if mode == 'tail':
            self.do_tail(path)
        elif mode == 'slow':
            self.do_slow(path)

    def do_slow(self, path: Path) -> None:
        fp = open(path, 'rb')
        bufsize = 4096
        while buf := fp.read(bufsize):
            #print(repr(buf))
            self.wfile.write(buf)
            self.wfile.flush()
            time.sleep(0.1)
            bufsize = 30

    def do_tail(self, path: Path) -> None:
        with Tail(path) as tail:
            print('hi')
            while True:
                r, _, x = select.select([tail, self.wfile], [], [])
                if self.wfile in r or self.wfile in x:
                    break
                if tail in r:
                    try:
                        self.wfile.write(tail.read(8192))
                        self.wfile.flush()
                    except BrokenPipeError:
                        break
        print('bye')
    


def main():
    httpd = ThreadingHTTPServer(('127.0.0.1', 8002), MyHTTPRequestHandler)
    httpd.serve_forever()
main()
