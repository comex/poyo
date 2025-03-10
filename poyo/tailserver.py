from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Optional
import subprocess

# lowest effort possible
class MyHTTPRequestHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if not self.path.endswith('?tail'):
            return super().do_GET()
        path = Path(self.translate_path(self.path))
        assert path.exists()
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        p: Optional[subprocess.Popen[bytes]] = None
        print('...')
        try:
            p = subprocess.Popen(['tail', '-c', '99999999', '-f', '--', path], stdout=subprocess.PIPE, bufsize=0)
            assert p.stdout is not None
            while buf := p.stdout.read(8192):
                print(repr(buf))
                self.wfile.write(buf)
                self.wfile.flush()
            print('it exited?')
        finally:
            if p is not None:
                p.terminate()
    


def main():
    httpd = ThreadingHTTPServer(('127.0.0.1', 8002), MyHTTPRequestHandler)
    httpd.serve_forever()
main()
