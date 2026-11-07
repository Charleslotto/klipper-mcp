"""Tests for the upload_gcode tool (tools/filesystem.py)."""
import asyncio
import http.server
import inspect
import json
import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import tools.filesystem as fs  # noqa: E402


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


@pytest.fixture
def upload_gcode():
    mcp = FakeMCP()
    fs.register_filesystem_tools(mcp)
    return mcp.tools["upload_gcode"]


@pytest.fixture
def uploads(monkeypatch):
    calls = []

    async def fake_upload(client, root, relative_path, content):
        calls.append((root, relative_path, content))
        return {"action": "create_file", "item": {"path": relative_path, "root": root}}

    monkeypatch.setattr(fs, "upload_to_moonraker", fake_upload)
    monkeypatch.setattr(fs, "get_client", lambda: object())
    return calls


def run(coro):
    return json.loads(asyncio.run(coro))


@pytest.fixture
def http_file():
    """Serve one in-memory file over HTTP on localhost; yields (set_body, base_url)."""
    state = {"body": b""}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/file.gcode":
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(state["body"])))
            self.end_headers()
            self.wfile.write(state["body"])

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def set_body(body):
        state["body"] = body

    yield set_body, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_takes_no_pin(upload_gcode):
    assert "pin" not in inspect.signature(upload_gcode).parameters


def test_uploads_content_to_gcodes_root(upload_gcode, uploads):
    out = run(upload_gcode("toy_house.gcode", content="G28\n"))
    assert out["success"] is True
    assert out["filepath"] == "gcodes/toy_house.gcode"
    assert uploads == [("gcodes", "toy_house.gcode", "G28\n")]
    assert out["moonraker_result"]["item"] == {"path": "toy_house.gcode", "root": "gcodes"}


def test_accepts_subdirectory(upload_gcode, uploads):
    out = run(upload_gcode("parts/toy_house.gcode", content="G28\n"))
    assert out["success"] is True
    assert uploads[0][:2] == ("gcodes", "parts/toy_house.gcode")


@pytest.mark.parametrize("name", ["printer.cfg", "toy_house.txt", "toy_house", "macros.cfg.gcode.sh"])
def test_rejects_non_gcode_names(upload_gcode, uploads, name):
    out = run(upload_gcode(name, content="G28\n"))
    assert "error" in out
    assert uploads == []


@pytest.mark.parametrize("name", ["../printer.gcode", "a/../../x.gcode", "/etc/x.gcode", "gcodes/../config/x.gcode"])
def test_rejects_paths_outside_gcodes(upload_gcode, uploads, name):
    out = run(upload_gcode(name, content="G28\n"))
    assert "error" in out
    assert uploads == []


def test_other_root_names_stay_inside_gcodes(upload_gcode, uploads):
    out = run(upload_gcode("config/x.gcode", content="G28\n"))
    assert out["filepath"] == "gcodes/config/x.gcode"
    assert uploads[0][:2] == ("gcodes", "config/x.gcode")


def test_requires_exactly_one_source(upload_gcode, uploads):
    assert "error" in run(upload_gcode("a.gcode"))
    assert "error" in run(upload_gcode("a.gcode", content="G28\n", url="http://x/a.gcode"))
    assert uploads == []


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://host/a.gcode", "not a url"])
def test_rejects_non_http_urls(upload_gcode, uploads, url):
    out = run(upload_gcode("a.gcode", url=url))
    assert "error" in out
    assert uploads == []


def test_downloads_url_and_uploads_bytes(upload_gcode, uploads, http_file):
    set_body, base = http_file
    set_body(b"G28\nG1 X10\n")
    out = run(upload_gcode("toy_house.gcode", url=f"{base}/file.gcode"))
    assert out["success"] is True
    assert out["bytes"] == 11
    assert uploads == [("gcodes", "toy_house.gcode", b"G28\nG1 X10\n")]


def test_reports_http_errors(upload_gcode, uploads, http_file):
    _, base = http_file
    out = run(upload_gcode("toy_house.gcode", url=f"{base}/missing.gcode"))
    assert "404" in out["error"]
    assert uploads == []


def test_refuses_downloads_over_the_size_limit(upload_gcode, uploads, http_file, monkeypatch):
    set_body, base = http_file
    monkeypatch.setattr(fs.config, "UPLOAD_MAX_BYTES", 10, raising=False)
    set_body(b"x" * 11)
    out = run(upload_gcode("big.gcode", url=f"{base}/file.gcode"))
    assert "limit" in out["error"]
    assert uploads == []


def test_refuses_content_over_the_size_limit(upload_gcode, uploads, monkeypatch):
    monkeypatch.setattr(fs.config, "UPLOAD_MAX_BYTES", 10, raising=False)
    out = run(upload_gcode("big.gcode", content="x" * 11))
    assert "limit" in out["error"]
    assert uploads == []


def test_reports_moonraker_errors(upload_gcode, monkeypatch):
    async def failing_upload(client, root, relative_path, content):
        return {"error": "disk full"}

    monkeypatch.setattr(fs, "upload_to_moonraker", failing_upload)
    monkeypatch.setattr(fs, "get_client", lambda: object())
    out = run(upload_gcode("a.gcode", content="G28\n"))
    assert out["error"] == "disk full"


def test_is_blocked_in_read_only_mode():
    import server
    assert not server.is_read_only_safe("upload_gcode")
