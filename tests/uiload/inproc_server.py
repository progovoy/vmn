"""``vmn-exp ui`` in-process (uvicorn on a thread) for the harness's own tests."""
import contextlib
import threading
import time

from uiload.ui_server import free_port

START_TIMEOUT_SEC = 20


@contextlib.contextmanager
def serve_root(root, data_dir, ws):
    """Serve *root* as workspace *ws*; yields ``(base_url, workspace name)``."""
    import uvicorn
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(str(data_dir))
    workspace = manager.attach_path(ws, str(root))
    app = create_app(manager, background_refresh=True)
    port = free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.time() + START_TIMEOUT_SEC
    while not srv.started and time.time() < deadline:
        time.sleep(0.05)
    assert srv.started, "ui server did not start"
    try:
        yield f"http://127.0.0.1:{port}", workspace.name
    finally:
        srv.should_exit = True
        thread.join(timeout=10)
        app.state.refresher.stop()
