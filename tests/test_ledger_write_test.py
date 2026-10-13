import pytest
from fastapi.testclient import TestClient
from app import main

TOKEN = "t" * 32
H = {"X-Paper-Ledger-Test-Token": TOKEN}


class FakeResult:
    def __init__(self, row=None, rowcount=1):
        self._row, self.rowcount = row, rowcount
    def first(self):
        return self._row


class FakeSession:
    def __init__(self, row=(1,), rowcount=1, fail_on=None):
        self.row, self.rowcount, self.fail_on = row, rowcount, fail_on
        self.sql, self.rolled_back, self.committed, self.closed = [], 0, 0, False
    def begin(self): pass
    def execute(self, stmt):
        s = str(stmt)
        self.sql.append(s)
        if self.fail_on and self.fail_on in s:
            raise RuntimeError("boom-secret-detail")
        if s.startswith("SELECT"):
            return FakeResult(self.row)
        if s.startswith("UPDATE"):
            return FakeResult(rowcount=self.rowcount)
        return FakeResult()
    def rollback(self): self.rolled_back += 1
    def commit(self): self.committed += 1
    def close(self): self.closed = True


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("PAPER_LEDGER_WRITE_TEST_TOKEN", TOKEN)
    monkeypatch.setattr(main.paper_ledger, "is_postgres_backend", lambda: True)
    return TestClient(main.app)


def use(monkeypatch, sess):
    monkeypatch.setattr(main.paper_ledger, "_get_session_factory", lambda: (lambda: sess))


def test_no_or_wrong_token_is_401_and_touches_no_db(client, monkeypatch):
    def boom():
        raise AssertionError("DB touched without auth")
    monkeypatch.setattr(main.paper_ledger, "_get_session_factory", boom)
    assert client.post("/api/ledger/write-test").status_code == 401
    assert client.post("/api/ledger/write-test", headers={"X-Paper-Ledger-Test-Token": "x"}).status_code == 401


def test_missing_env_token_disables_endpoint(client, monkeypatch):
    monkeypatch.delenv("PAPER_LEDGER_WRITE_TEST_TOKEN")
    assert client.post("/api/ledger/write-test", headers=H).status_code == 401


def test_token_ok_handles_non_ascii():
    assert main._token_ok("ééé", TOKEN) is False


def test_success_always_rolls_back_never_commits(client, monkeypatch):
    s = FakeSession(); use(monkeypatch, s)
    r = client.post("/api/ledger/write-test", headers=H)
    d = r.json()
    assert r.status_code == 200
    assert d["write_test"] == "passed_rolled_back" and d["ledger_changes_committed"] is False
    assert s.committed == 0 and s.rolled_back >= 1 and s.closed
    assert any("FOR UPDATE" in q for q in s.sql) and any("lock_timeout" in q for q in s.sql)


def test_rowcount_not_one_fails_and_rolls_back(client, monkeypatch):
    s = FakeSession(rowcount=2); use(monkeypatch, s)
    r = client.post("/api/ledger/write-test", headers=H)
    assert r.status_code == 503 and r.json()["write_test"] == "failed"
    assert s.committed == 0 and s.rolled_back >= 1 and s.closed


def test_missing_row_fails_and_rolls_back(client, monkeypatch):
    s = FakeSession(row=None); use(monkeypatch, s)
    assert client.post("/api/ledger/write-test", headers=H).status_code == 503
    assert s.committed == 0 and s.rolled_back >= 1


def test_exception_rolls_back_and_does_not_leak_detail(client, monkeypatch):
    s = FakeSession(fail_on="UPDATE"); use(monkeypatch, s)
    r = client.post("/api/ledger/write-test", headers=H)
    assert r.status_code == 503 and "boom-secret-detail" not in r.text
    assert s.committed == 0 and s.rolled_back >= 1 and s.closed
