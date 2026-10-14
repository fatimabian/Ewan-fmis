from io import BytesIO, StringIO


def prewarm_wsgi_application(application, host="localhost"):
    """Run one secure landing-page request before the server accepts traffic."""
    captured = {}

    def start_response(status, headers, exc_info=None):
        captured["status"] = status
        captured["headers"] = headers

    server_name, _, port = host.partition(":")
    environ = {
        "REQUEST_METHOD": "GET",
        "SCRIPT_NAME": "",
        "PATH_INFO": "/",
        "QUERY_STRING": "",
        "SERVER_NAME": server_name or "localhost",
        "SERVER_PORT": port or "443",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "CONTENT_TYPE": "",
        "CONTENT_LENGTH": "0",
        "HTTP_HOST": host,
        "REMOTE_ADDR": "127.0.0.1",
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": "https",
        "wsgi.input": BytesIO(b""),
        "wsgi.errors": StringIO(),
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": True,
    }
    response = application(environ, start_response)
    try:
        for _ in response:
            pass
    finally:
        close = getattr(response, "close", None)
        if close:
            close()

    status_code = int(captured.get("status", "500").split(" ", 1)[0])
    if not 200 <= status_code < 400:
        raise RuntimeError(f"FMIS startup readiness request returned HTTP {status_code}.")
    return status_code
