"""The job page's answers, run search and baselines, built from an index
snapshot still loading, say so with ``indexing {loaded, total}`` and an ETag
that follows the load, like the board's (plan 33 §2.2)."""
import pytest

pytest.importorskip("fastapi")

from test_ui_board_indexing import BASE, PARENT, board  # noqa: E402,F401

ANSWERS = [
    f"{BASE}/experiments/{PARENT}/summary",
    f"{BASE}/experiments/{PARENT}/failures",
    f"{BASE}/search?text=1",
    f"{BASE}/experiments/{PARENT}/baseline",
    f"{BASE}/experiments-baselines?v={PARENT}",
]


@pytest.mark.parametrize("url", ANSWERS)
def test_a_job_page_answer_says_the_index_is_still_loading(board, url):  # noqa: F811
    client, loading = board
    loading.state = (2, 734_000)
    answer = client.get(url)
    assert answer.status_code == 200, answer.text
    assert answer.json()["indexing"] == {"loaded": 2, "total": 734_000}


@pytest.mark.parametrize("url", ANSWERS)
def test_a_loaded_index_answers_the_job_page_without_indexing(board, url):  # noqa: F811
    client, _ = board
    answer = client.get(url)
    assert answer.status_code == 200, answer.text
    assert "indexing" not in answer.json()


@pytest.mark.parametrize("url", ANSWERS)
def test_a_job_page_etag_moves_with_the_load_and_when_it_ends(board, url):  # noqa: F811
    client, loading = board
    loading.state = (1, 10)
    first = client.get(url)
    loading.state = (5, 10)
    later = client.get(url, headers={"If-None-Match": first.headers["etag"]})
    loading.state = None
    done = client.get(url, headers={"If-None-Match": later.headers["etag"]})

    assert later.status_code == 200 and later.json()["indexing"]["loaded"] == 5
    assert done.status_code == 200 and "indexing" not in done.json()
