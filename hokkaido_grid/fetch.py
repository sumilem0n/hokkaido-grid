"""One retrying GET, shared by every source module.

Sources differ in what they parse; they do not differ in what a flaky HTTP
endpoint looks like. hepco_daily classifies a *response*; this classifies an
*attempt*, and only hands back a body it is willing to stand behind.

The two failure shapes -- no response at all (ConnectionError, Timeout) and a
response with a retryable status -- converge on the same question: sleep how
long, and is there time left to sleep at all. So the loop has exactly one
sleep and exactly one give-up path, and the branches above it do nothing but
set `cause` (and, for a status, a server-supplied delay).

Named fetch, not http: hokkaido_grid.http would shadow the stdlib http
package for anything inside this package. Absolute imports make that mostly
harmless, and mostly harmless is a poor trade against a one-word rename.
"""

import logging
import time

import requests

from hokkaido_grid.errors import SourceTransientError, SourceUnavailable

MAX_ATTEMPTS = 4
BASE_DELAY = 1.0
MAX_DELAY = 30.0
DEADLINE = 120.0
TIMEOUT = (5.0, 30.0)  # (connect, read)

# 429 and the three gateway-ish 5xx. Not 500: a bare 500 from a static CSV
# host is not a load signal, it is a broken host, and four attempts against
# it buys nothing. Add it the day one is observed to clear on retry. Weaker
# if a reverse proxy sits in front of HEPCO -- proxies emit 500 for upstream
# trouble -- so expect this line to move.
RETRYABLE_STATUS = frozenset({429, 502, 503, 504})

log = logging.getLogger(__name__)


def get_text(url, encoding=None):
    """GET `url` with retries; return the body as text, or raise.

    `encoding` is decoded strictly from the raw bytes when given. The default
    leaves it to requests, which guesses. Callers with a known charset should
    pass it -- for jisseki that is cp932, where a byte that will not decode
    means the file changed and the UnicodeDecodeError is the point.

    Raises SourceUnavailable, carrying .status_code, on any status outside
    RETRYABLE_STATUS. Raises SourceTransientError when attempts or the
    deadline run out.
    """
    deadline = time.monotonic() + DEADLINE

    for attempt in range(1, MAX_ATTEMPTS + 1):
        retry_after = None
        try:
            resp = requests.get(url, timeout=TIMEOUT)
        except (requests.ConnectionError, requests.Timeout,
                requests.exceptions.ChunkedEncodingError,
                requests.exceptions.ContentDecodingError) as exc:
            # No response, or one that died mid-stream. Nothing to inspect,
            # always retry-shaped. The two decoding errors are caught by name
            # because they subclass RequestException rather than the two
            # above: a body that starts arriving and stops is a bad link, not
            # a bad argument, and it would otherwise escape both of this
            # module's exception types entirely.
            #
            # Other RequestExceptions -- InvalidURL, TooManyRedirects -- are
            # not caught on purpose: those are wrong arguments, not a bad
            # network, and retrying a wrong argument four times only delays
            # the traceback.
            cause = f"{type(exc).__name__}: {exc}"
        else:
            if resp.status_code == 200:
                if encoding:
                    return resp.content.decode(encoding, errors="strict")
                return resp.text
            if resp.status_code not in RETRYABLE_STATUS:
                # 404, 403, 410: the server answered, and the answer is no.
                # status_code rides along because the caller's meaning for 404
                # depends on the day's age, which is not knowable here.
                raise SourceUnavailable(
                    f"HTTP {resp.status_code} for {url}",
                    status_code=resp.status_code,
                )
            cause = f"HTTP {resp.status_code}"
            retry_after = _retry_after(resp)

        # -- one sleep site, one give-up site, both branches arrive here --

        if attempt == MAX_ATTEMPTS:
            reason = f"{MAX_ATTEMPTS} attempts exhausted"
            break

        delay = _delay(attempt, retry_after)
        remaining = deadline - time.monotonic()
        if delay > remaining:
            # Give up now rather than sleep into the deadline and wake up to
            # fail anyway. Under cron the whole run has a budget; burning 30s
            # of it to reach a foregone conclusion is worse than reporting it.
            reason = (
                f"deadline: {remaining:.1f}s of {DEADLINE:.0f}s left, "
                f"next delay {delay:.1f}s"
            )
            break

        log.warning(
            "%s: attempt %d/%d failed (%s), retrying in %.1fs",
            url, attempt, MAX_ATTEMPTS, cause, delay,
        )
        time.sleep(delay)

    log.error("%s: giving up -- %s; last failure: %s", url, reason, cause)
    raise SourceTransientError(f"{url}: {reason}; last failure: {cause}")


def _delay(attempt, retry_after):
    """Seconds to wait before `attempt` + 1."""
    # Retry-After overrides the formula rather than adding to it or being
    # ignored. The formula is a guess about a server we cannot see; Retry-After
    # is that server saying when it will be ready. Adding them means the one
    # case where we are told the answer is the case we wait longest in, for no
    # reason. Ignoring it means the 429 branch keeps arriving early and being
    # refused again.
    #
    # It overrides upward and downward: a server asking us to come back sooner
    # than the backoff is still the better-informed party, and MAX_ATTEMPTS
    # bounds the hammering either way. Zero is the exception -- see _retry_after.
    #
    # MAX_DELAY and the deadline still bind. A server can say when it wants us
    # back; it does not get to set our budget, or an hour-long Retry-After
    # would park a cron job until the next one laps it.
    if retry_after is not None:
        return min(retry_after, MAX_DELAY)
    return min(BASE_DELAY * 2 ** (attempt - 1), MAX_DELAY)


def _retry_after(resp):
    """Retry-After in seconds, or None if absent, non-integer, or zero.

    Delta-seconds only. The HTTP-date form is legal and has never been seen
    from either source; parsing it means trusting the server's clock against
    ours, which is a decision worth making when something actually sends one.
    Until then an unparseable value falls back to the formula rather than
    failing -- the header is advice, not schema.

    Zero is treated as absent, deliberately. A server that has just refused us
    and then asks for an immediate return is misconfigured or worse, and
    obeying it literally turns four attempts into four with no gap at all --
    the backoff never runs. urllib3 reaches the same behaviour by accident,
    testing `if retry_after:` where a falsy 0 slips through to its own
    backoff; here it is a decision.
    """
    raw = resp.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        seconds = int(raw.strip())
    except ValueError:
        log.warning("ignoring non-integer Retry-After %r", raw)
        return None
    if seconds <= 0:
        log.warning("ignoring Retry-After %r, using backoff", raw)
        return None
    return seconds
