from pathlib import Path
from typing import Optional
import re
import time
import select
import aiohttp
from aiohttp import web
import asyncio
from pathlib import Path

from .common import Tail, latest_log, log_dir

# (started as) lowest effort possible
#class MyHTTPRequestHandler(SimpleHTTPRequestHandler):
#    def do_GET(self):
#        if not (m := re.search(r'\?(tail|slow)$', self.path)):
#            return super().do_GET()
#        mode = m[1]
#        path = Path(self.translate_path(self.path))
#        assert path.exists()
#        self.send_response(200)
#        self.send_header('Content-Type', 'text/html')
#        self.end_headers()
#        print('...')
#        if mode == 'tail':
#            self.do_tail(path)
#        elif mode == 'slow':
#            self.do_slow(path)

#    def do_slow(self, path: Path) -> None:
#        fp = open(path, 'rb')
#        bufsize = 4096
#        while buf := fp.read(bufsize):
#            #print(repr(buf))
#            self.wfile.write(buf)
#            self.wfile.flush()
#            time.sleep(0.1)
#            bufsize = 30

#    def do_tail(self, path: Path) -> None:
#        with Tail(path) as tail:
#            print('hi')
#            while True:
#                r, _, x = select.select([tail, self.wfile], [], [])
#                if self.wfile in r or self.wfile in x:
#                    break
#                if tail in r:
#                    try:
#                        self.wfile.write(tail.read(8192))
#                        self.wfile.flush()
#                    except BrokenPipeError:
#                        break
#        print('bye')

async def handle_render(request: web.Request) -> web.StreamResponse:
    name = request.match_info['name']
    tail = 'tail' in request.query

    if name == 'latest':
        name = latest_log().name
    assert '/' not in name and name.endswith('.txt')

    log_path = log_dir / name
    fp = open_tail(log_path) if tail else open(log_path)
    with fp:
        for bit in filtered_log_to_html(filter_log(load_jsonl(fp))):


def create_app() -> web.Application:
    app = web.Application()
    app.add_routes([
        web.get(r'/render/{name:(log([0-9]+)\.txt|latest)}', handle_render),
    ])
    app.router.add_static('/', '.', show_index=True)

    return app

if __name__ == '__main__':
    web.run_app(
        create_app(),
        host='127.0.0.1',
        port=8002,
        handler_cancellation=True
    )
