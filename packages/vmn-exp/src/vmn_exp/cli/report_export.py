"""``vmn-exp report export``: one self-contained HTML file of a report
revision (docs/plans/13-reports-comments.md §6) — the markdown, its
published panel data and media inlined, and the renderer bundle built from
``webui/src/reports/export.tsx`` (``webui/vite.export.config.ts``)."""
import base64
import html
import json
import mimetypes
import os

from vmn_exp.reports import published

BUNDLE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui", "export_bundle")
VMN_SCHEME = "vmn://"


def load_bundle():
    """``(js, css)`` of the built export renderer."""
    def read(name):
        with open(os.path.join(BUNDLE_DIR, name), encoding="utf-8") as f:
            return f.read()
    return read("report-export.js"), read("report-export.css")


def panel_payloads(storage, rid, rev):
    """``{panel-id: payload}`` revision *rev* published (empty if none)."""
    return {pid: published.panel_data(storage, rid, rev, pid)
            for pid in published.panel_ids(storage, rid, rev)}


def _local_path(storage, uri):
    """The stored file of ``vmn://<app>/<verstr>/<path>`` (app names may hold
    ``/``, so try each split), or None."""
    parts = uri[len(VMN_SCHEME):].split("/")
    for i in range(1, len(parts) - 1):
        app, verstr, path = "/".join(parts[:i]), parts[i], "/".join(parts[i + 1:])
        local = storage.artifact_local_path(app, verstr, path)
        if local:
            return local
    return None


def _data_uri(path):
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    with open(path, "rb") as f:
        return f"data:{mime};base64,{base64.b64encode(f.read()).decode('ascii')}"


def collect_media(storage, panels, cap_bytes):
    """``({uri: data-uri}, skipped)``: every panel's media, in order, while
    their total size stays within *cap_bytes*; missing or over-cap ones skip."""
    media, skipped, total = {}, [], 0
    uris = dict.fromkeys(uri for p in panels.values() for uri in p.get("media") or ())
    for uri in uris:
        local = _local_path(storage, uri) if uri.startswith(VMN_SCHEME) else None
        size = os.path.getsize(local) if local else None
        if size is None or total + size > cap_bytes:
            skipped.append(uri)
            continue
        total += size
        media[uri] = _data_uri(local)
    return media, skipped


def _script_safe(text):
    return text.replace("</", "<\\/")


def _json_safe(data):
    return json.dumps(data).replace("<", "\\u003c")


def build_html(data, js, css):
    """The page: styles, the report data as JSON, then the renderer."""
    return (
        "<!doctype html>\n<html><head><meta charset=\"utf-8\">"
        f"<title>{html.escape(data['title'])}</title>\n<style>{_script_safe(css)}</style></head>\n"
        "<body><div id=\"root\"></div>\n"
        f"<script type=\"application/json\" id=\"vmn-report-data\">{_json_safe(data)}</script>\n"
        f"<script>{_script_safe(js)}</script>\n</body></html>\n"
    )
