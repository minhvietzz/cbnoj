"""
Optional Safe Exam Browser (SEB) enforcement.

SEB sends `X-SafeExamBrowser-RequestHash` with every request: the SHA-256 of the absolute URL it requested
followed by the exam's Browser Exam Key. The server recomputes it with the key stored on the quiz, so a normal
browser (which does not know the key) is refused. The URL must be what the browser requested, so the proxy has to
pass the original Host header and scheme through.
"""
import hashlib
import hmac

HEADER = 'HTTP_X_SAFEEXAMBROWSER_REQUESTHASH'


def expected_hash(url, key):
    return hashlib.sha256((url + key).encode('utf-8')).hexdigest()


def request_ok(request, key):
    """True when no key is required, or when the request carries a valid hash for `key`."""
    if not key:
        return True
    given = request.META.get(HEADER, '').strip().lower()
    return bool(given) and hmac.compare_digest(given, expected_hash(request.build_absolute_uri(), key))
