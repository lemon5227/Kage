"""Resettable local browser task with independently readable backend state."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading

HTML_PATH = Path(__file__).resolve().parents[2]/'tests/fixtures/computer-use/profile.html'


@contextmanager
def profile_server():
    state={'saved':None,'posts':0}
    html=HTML_PATH.read_bytes()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            data=json.dumps(state['saved']).encode() if self.path=='/record' else html
            self.send_response(200)
            self.send_header('Content-Type','application/json' if self.path=='/record' else 'text/html; charset=utf-8')
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Length',str(len(data)))
            self.end_headers();self.wfile.write(data)
        def do_POST(self):
            if self.path != '/save':
                self.send_error(404);return
            state['saved']=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state['posts']+=1
            data=json.dumps(state['saved']).encode()
            self.send_response(200);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def log_message(self,*args): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}',state
    finally:
        server.shutdown();server.server_close();thread.join()
