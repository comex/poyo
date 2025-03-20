from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Optional
import subprocess
import re
import time

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
        p: Optional[subprocess.Popen[bytes]] = None
        try:
            p = subprocess.Popen(['tail', '-c', '99999999', '-f', '--', path], stdout=subprocess.PIPE, bufsize=0)
            assert p.stdout is not None
            while buf := p.stdout.read(8192):
                #print(repr(buf))
                self.wfile.write(buf)
                self.wfile.flush()
                #import time; time.sleep(0.5)
            print('it exited?')
        finally:
            if p is not None:
                p.terminate()
    


def main():
    httpd = ThreadingHTTPServer(('127.0.0.1', 8002), MyHTTPRequestHandler)
    httpd.serve_forever()
main()
