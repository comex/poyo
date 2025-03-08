import http.server

class RequestHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        print(self.headers)
        f = self.send_head()
        if f:
            try:
                f.write('ho\n')
            finally:
                f.close()

def main():
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 25192), RequestHandler)
    server.serve_forever()
if __name__ == '__main__': main()
