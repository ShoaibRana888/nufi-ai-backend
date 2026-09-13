# utils/errors.py
"""What a handler says when it fails.

Every `api/` handler ends in `except Exception as e:` and used to answer with
`HTTPException(500, detail=str(e))` -- 96 of them, plus 13 `{'error': str(e)}`
bodies and two f-strings. Two things were wrong with that, and this module
fixes both in one place:

* **The text.** `str(e)` for a PostgREST failure is the SQL message, the
  Postgres error code and a hint naming tables and columns; for an HTTP
  failure it is the request URL with the project host. No route has auth.
  The client reads `detail` only as display text with a fallback (sixteen
  `errorData['detail'] ?? 'Failed to ...'` sites), never for structure, so a
  generic message costs it nothing. The real exception goes to the server
  log, where it was already being printed.

* **The status.** Most handlers raise their 4xx *inside* the `try`, and the
  bare `except Exception` below caught it and re-raised it as a 500 whose
  detail was "404: User not found". `internal_error` hands an HTTPException
  back unchanged, so a 404 stays a 404.

Use: `raise internal_error(e)` in the `except`, or `public_message(e)` where
the handler answers 200 with an error field. `tests/test_no_exception_text_in_responses.py`
fails on any `str(e)` that finds its way back into a response.
"""
import traceback

from fastapi import HTTPException

INTERNAL_ERROR_DETAIL = "Something went wrong on our side. Please try again."


def public_message(e: BaseException) -> str:
    """The text a response may carry for `e`: its own, if it is an HTTPException
    the handler raised deliberately; the generic message otherwise."""
    if isinstance(e, HTTPException):
        return str(e.detail)
    return INTERNAL_ERROR_DETAIL


def internal_error(e: BaseException) -> HTTPException:
    """The HTTPException to raise from a handler's catch-all `except`.

    A deliberate HTTPException passes through with its own status and
    detail. Anything else is logged with its traceback and answered as a 500
    with the generic message.
    """
    if isinstance(e, HTTPException):
        return e
    print(f"❌ Unhandled {type(e).__name__}: {e}")
    traceback.print_exc()
    return HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL)
