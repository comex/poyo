from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import re
from typing import Any, Iterable
from urllib.parse import urlparse, parse_qs
from dataclasses import dataclass
import select
import threading
import time

from poyo.log import filter_log, filtered_log_to_html, load_jsonl

from .common import latest_log, open_tail

@dataclass
class Resp:
    content_type: str
    data: Iterable[str]


TEXT_HTML = 'text/html; charset=utf-8'
TEXT_PLAIN = 'text/plain; charset=utf-8'

def slow_filter(r: Resp) -> Resp:
    def data():
        written_so_far = 0
        for blob in r.data:
            while blob:
                bufsize = min(len(blob), max(30, 4096 - written_so_far))
                yield blob[:bufsize]
                time.sleep(0.2)
                blob = blob[bufsize:] # n^2 don't care

    return Resp(r.content_type, data())

def render_filter(r: Resp) -> Resp:
    assert r.content_type == TEXT_PLAIN
    return Resp(
        TEXT_HTML,
        filtered_log_to_html(filter_log(load_jsonl(r.data)))
    )

def initial_resp(path: Path, tail: bool, wfile_for_interrupt: Any) -> Resp:
    fp = open_tail(path) if tail else open(path)
    def initial_data():
        while True:
            # must select to avoid python deadlocks
            r, _w, _x = select.select([fp, wfile_for_interrupt], [], [])
            if wfile_for_interrupt in r:
                break
            assert fp in r
            blob = fp.read(4096)
            if not blob:
                break
            yield blob
    ctype = TEXT_HTML if path.name.endswith('.html') else TEXT_PLAIN
    return Resp(ctype, initial_data())

# (started as) lowest effort possible
class MyHTTPRequestHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        self.path = re.sub(r'^/log/log', '/log', self.path) # meh
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query, keep_blank_values=True)
        if parsed.path == '/log/latest':
            self.path = '/log/' + latest_log().name

        if not query:
            return super().do_GET()


        path = Path(self.translate_path(self.path))
        assert path.exists(), path
        tail = False
        if 'tail' in query:
            tail = True
            del query['tail']

        resp = initial_resp(path, tail, self.wfile)
        for filter_name in query:
            match filter_name:
                case 'slow':
                    resp = slow_filter(resp)
                case 'render':
                    resp = render_filter(resp)
                case _:
                    raise Exception(f'invalid filter {filter_name!r}')

        self.send_response(200)
        self.send_header('Content-Type', resp.content_type)
        self.end_headers()

        for chunk in resp.data:
            self.wfile.write(chunk.encode())
            self.wfile.flush()
        print('bye')


def main():
    httpd = ThreadingHTTPServer((
        #'127.0.0.1',
        '0.0.0.0',
    8002), MyHTTPRequestHandler)
    httpd.serve_forever()
main()
