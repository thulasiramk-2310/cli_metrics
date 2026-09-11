"""MetricsSender tests: the HTTP path to the backend, without a backend.

`requests` is an optional dependency, so every test here fakes it rather than
requiring it to be installed.
"""

import pytest

import sysdash.collector as collector_module
from sysdash.collector import MetricsSender


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class FakeRequests:
    """Stands in for the requests module, recording calls and replaying results.

    ``result`` is either a FakeResponse to return or an exception to raise.
    """

    def __init__(self, result):
        self.result = result
        self.posts = []
        self.gets = []
        self.exceptions = _RequestsExceptions()

    def _replay(self):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return self._replay()

    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        return self._replay()


class _RequestsExceptions:
    """The exception classes MetricsSender catches by name."""

    class RequestException(Exception):
        pass

    class ConnectionError(RequestException):
        pass

    class Timeout(RequestException):
        pass


@pytest.fixture
def sender(monkeypatch):
    """Build a sender against a fake requests module chosen per test."""

    def build(result=None):
        fake = FakeRequests(FakeResponse(200) if result is None else result)
        # raising=False: requests is an optional dependency, so the name may
        # not exist on the module at all when it is not installed.
        monkeypatch.setattr(collector_module, "requests", fake, raising=False)
        monkeypatch.setattr(collector_module, "HAS_REQUESTS", True)
        instance = MetricsSender(backend_url="http://backend:8080/")
        instance.requests = fake
        return instance

    return build


def test_missing_requests_is_an_actionable_error(monkeypatch):
    monkeypatch.setattr(collector_module, "HAS_REQUESTS", False)
    with pytest.raises(ImportError, match="pip install requests"):
        MetricsSender()


def test_trailing_slash_does_not_double_up(sender):
    """A URL pasted with a trailing slash must not produce //api/metrics."""
    assert sender().metrics_endpoint == "http://backend:8080/api/metrics"


def test_a_200_is_a_success(sender):
    instance = sender()
    assert instance.send_metrics({"cpu": 1}) is True

    url, kwargs = instance.requests.posts[0]
    assert url == "http://backend:8080/api/metrics"
    assert kwargs["json"] == {"cpu": 1}
    assert kwargs["timeout"] == instance.timeout


def test_a_non_200_is_a_failure_not_a_crash(sender):
    assert sender(FakeResponse(503)).send_metrics({}) is False


@pytest.mark.parametrize(
    "error",
    [
        _RequestsExceptions.ConnectionError("refused"),
        _RequestsExceptions.Timeout("too slow"),
        _RequestsExceptions.RequestException("malformed"),
    ],
)
def test_transport_errors_are_reported_as_failure(sender, error):
    """A backend that is down must not take the collector down with it."""
    assert sender(error).send_metrics({}) is False


def test_a_programming_error_is_not_swallowed(sender):
    """Only transport failures are caught.

    An unserialisable metrics dict raises TypeError, which is a bug here. It
    used to be caught by a bare `except Exception` and logged as if the network
    had hiccuped.
    """
    instance = sender(TypeError("Object of type set is not JSON serializable"))
    with pytest.raises(TypeError):
        instance.send_metrics({"bad": {1, 2}})


def test_health_check_passes_on_200(sender):
    instance = sender()
    assert instance.check_backend_health() is True
    assert instance.requests.gets[0][0] == "http://backend:8080/health"


def test_health_check_fails_when_unreachable(sender):
    error = _RequestsExceptions.ConnectionError("refused")
    assert sender(error).check_backend_health() is False
