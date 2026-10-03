"""Plan 13 §6: ``vmn-exp report export`` builds one self-contained HTML file."""
import json
import os
import shutil
import subprocess

import pytest

from vmn_exp.cli import report_export as rx

PNG = b"\x89PNG\r\n\x1a\nfake"


class FakeStorage:
    def __init__(self, files):
        self.files = files

    def artifact_local_path(self, app, verstr, name):
        return self.files.get((app, verstr, name))


def _payload(media=()):
    return {"ws": "w", "app": "root/svc", "verstrs": ["0.0.1-dev.ab"], "media": list(media), "queries": []}


def test_media_inlined_as_data_uris_up_to_the_cap(tmp_path):
    small, big = tmp_path / "s.png", tmp_path / "b.png"
    small.write_bytes(PNG)
    big.write_bytes(PNG * 100)
    storage = FakeStorage({("root/svc", "v1", "media/i/1.png"): str(small),
                           ("root/svc", "v1", "media/i/2.png"): str(big)})
    uris = ["vmn://root/svc/v1/media/i/1.png", "vmn://root/svc/v1/media/i/2.png", "vmn://root/svc/v1/media/gone.png"]
    media, skipped = rx.collect_media(storage, {"p": _payload(uris)}, cap_bytes=len(PNG) * 10)
    assert media == {uris[0]: "data:image/png;base64,iVBORw0KGgpmYWtl"}
    assert skipped == uris[1:]


def test_zero_cap_inlines_nothing(tmp_path):
    f = tmp_path / "s.png"
    f.write_bytes(PNG)
    storage = FakeStorage({("a", "v1", "media/x.png"): str(f)})
    assert rx.collect_media(storage, {"p": _payload(["vmn://a/v1/media/x.png"])}, 0) == ({}, ["vmn://a/v1/media/x.png"])


def test_html_is_self_contained_and_escapes_script_ends():
    data = {"title": "T </script><b>", "rev": 1, "body": "# T\n\n</script>", "panels": {}, "media": {}}
    html = rx.build_html(data, js="console.log(1)", css="body{}")
    assert html.count("</script>") == 2  # the data block and the bundle
    assert "<script src" not in html and "<link" not in html
    start = html.index('id="vmn-report-data">') + len('id="vmn-report-data">')
    assert json.loads(html[start:html.index("</script>", start)]) == data
    assert "<title>T &lt;/script&gt;&lt;b&gt;</title>" in html


def test_bundle_ships_with_the_package():
    js, css = rx.load_bundle()
    assert "vmn-report-data" in js and css


NODE = shutil.which("node")
JSDOM = os.path.join(os.path.dirname(__file__), "..", "webui", "node_modules", "jsdom")

SCRIPT = """
const { JSDOM, VirtualConsole } = require(process.argv[2]);
const html = require("fs").readFileSync(process.argv[3], "utf8");
const requests = [];
const vc = new VirtualConsole(); vc.on("jsdomError", (e) => console.error(e.message));
// jsdom lacks matchMedia, and an opaque origin has no sessionStorage.
const beforeParse = (w) => {
  w.fetch = (u) => { requests.push(String(u)); return Promise.reject(new Error("offline")); };
  w.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
};
const dom = new JSDOM(html, { runScripts: "dangerously", virtualConsole: vc, url: "https://report.invalid/", beforeParse });
setTimeout(() => {
  const d = dom.window.document;
  console.log(JSON.stringify({ text: d.getElementById("root").textContent, requests,
    img: [...d.querySelectorAll("img")].map((i) => i.getAttribute("src")) }));
}, 500);
"""


@pytest.mark.skipif(not NODE or not os.path.isdir(JSDOM), reason="needs node + webui/node_modules")
def test_exported_html_renders_offline_in_jsdom(tmp_path):
    detail = {"metadata": {"verstr": "v1"}, "metrics": {"acc_metric": 0.9}, "params": {"lr_param": 0.1},
              "series": {}, "patches": {}, "status": {"status": "succeeded", "exit_code": 0},
              "media": {"img": [{"step": 1, "path": "media/img/1.png"}]}}
    key = ["experiment", "w", "my_app", "v1"]
    payload = {"ws": "w", "app": "my_app", "verstrs": ["v1"], "media": [], "queries": [{"key": key, "data": detail}]}
    block = lambda pid, typ, extra="": (f'```vmn-panel\n{{"v": 1, "id": "{pid}", "app": "my_app", '
                                         f'"type": "{typ}", "runs": {{"verstrs": ["v1"]}}{extra}}}\n```\n\n')
    body = "# Exported heading\n\n" + block("card", "run") + block("pic", "media", ', "key": "img"') + \
        block("none", "run")
    data = {"title": "T", "rev": 1, "body": body, "panels": {"card": payload, "pic": payload},
            "media": {"vmn://my_app/v1/media/img/1.png": "data:image/png;base64,AAAA"}}
    out = tmp_path / "r.html"
    out.write_text(rx.build_html(data, *rx.load_bundle()))
    script = tmp_path / "check.js"
    script.write_text(SCRIPT)
    res = subprocess.run([NODE, str(script), os.path.abspath(JSDOM), str(out)],
                         capture_output=True, text=True, timeout=60)
    result = json.loads(res.stdout.strip().splitlines()[-1])
    assert "Exported heading" in result["text"]
    assert "acc_metric" in result["text"] and "lr_param" in result["text"]
    assert "No published data for this panel" in result["text"]
    assert "data:image/png;base64,AAAA" in result["img"]
    assert result["requests"] == []
