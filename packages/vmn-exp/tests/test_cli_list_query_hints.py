"""Plan 31 §4.2: ``vmn-exp list --query`` matching nothing says on stderr
when the row field's value sits under ``tags.<field>`` instead."""
from exp_helpers import _bootstrap, _exp, _storage
from similar_seed import WRITER, seed, verstr

from vmn_exp.core.writer import create_tags_entry

HINT = 'kind = "launch" matches nothing; did you mean tags.kind?'


def _list(app, capfd, query):
    capfd.readouterr()
    code = _exp(app, action="list", extra_args=["--query", query])
    out = capfd.readouterr()
    assert code == 0, out.err
    return out


def test_an_empty_list_hints_at_the_tag(app_layout, capfd):
    _bootstrap(app_layout)
    app, storage = app_layout.app_name, _storage(app_layout)
    seed(storage, app, verstr(1), exit_code=0)
    storage.append_log_entry(app, verstr(1), WRITER, create_tags_entry({"kind": "launch"}))
    assert HINT in _list(app, capfd, 'kind = "launch"').err
    assert HINT not in _list(app, capfd, 'tags.kind = "launch"').err
    assert "matches nothing" not in _list(app, capfd, 'kind = "other"').err
