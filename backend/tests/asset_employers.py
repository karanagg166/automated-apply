"""Owned loopback static server. No real CDN, account, telemetry or job submission."""

import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@contextmanager
def static_site():
    class Requests(list):
        started = threading.Event()
        release = threading.Event()

    requests = Requests()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append({"path": self.path, "headers": dict(self.headers)})
            if self.path == "/slow.js":
                requests.started.set()
                requests.release.wait(timeout=20)
            if self.path == "/redirect.js":
                self.send_response(302)
                self.send_header("Location", "/never.js")
                self.end_headers()
                return
            if self.path == "/auth.js":
                self.send_response(401)
                self.end_headers()
                return
            kind = (
                "text/css" if self.path.endswith(".css") else "application/javascript"
            )
            body = b"document.documentElement.dataset.fixtureAsset='loaded';"
            if self.path == "/form.js":
                body = b"""document.getElementById('application').innerHTML = `<form method=post action=/receipt>
                  <label>Full name<input name=name required></label>
                  <label>Email<input name=email type=email required></label>
                  <label>Notice period<input name=notice required></label>
                  <label>Upload resume<input type=file accept='.pdf' required></label>
                  <label>I consent to data processing<input type=checkbox required></label>
                  <button type=submit>Submit application</button></form>`;
                  if(window.fixtureLate) document.querySelector('[name=name]').addEventListener('input',()=>{
                    const s=document.createElement('script');s.src=window.fixtureAssets+'/late.js';document.head.append(s);
                  });"""
            elif self.path.endswith(".css"):
                body = b"#application { border: 3px solid rgb(10,20,30); }"
            elif self.path == "/wrong.js":
                kind, body = "text/html", b"<h1>Sign in to access this resource</h1>"
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Set-Cookie", "asset_poison=fixture-only; Path=/")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        requests.release.set()
        server.shutdown()
        server.server_close()
        thread.join()


def application_html(assets, *, script="form.js", late=False):
    return f"""<h1>Example Circuit — Backend Engineer asset fixture</h1>
      <script>document.cookie='application_session=fictional-owned-session; path=/';
      window.fixtureAssets='{assets}';window.fixtureLate={str(late).lower()};</script>
      <div id=application></div><link rel=stylesheet href='{assets}/theme.css'>
      <script crossorigin=anonymous src='{assets}/{script}'></script>"""
