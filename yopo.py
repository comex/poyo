import http.server
from http import HTTPStatus
import time

class RequestHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        print(self.headers)
        self.send_response(HTTPStatus.OK)
        self.end_headers()
        self.wfile.write(b'ho\n')
        time.sleep(1)

def main():
    listen = ('127.0.0.1', 25192)
    server = http.server.ThreadingHTTPServer(listen, RequestHandler)
    print('listening on', listen)
    server.serve_forever()
if __name__ == '__main__': main()
