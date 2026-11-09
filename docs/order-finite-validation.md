# Offline regression: non-finite order quantities

`App._send_order` must reject NaN and infinity before creating a worker.
`float()` accepts these values; comparison with the exchange maximum alone
is insufficient. Even a lower-bound check does not reject NaN.

Run with an existing Python interpreter, from the repository root:

    python -I -B tests/test_order_finite.py

The standard-library test parses moongui.py and compiles only the actual
_send_order method. It never imports the GUI module (which creates runtime
folders). GUI values, credentials, order functions and Thread are synthetic
objects. No worker, network call, GUI window or agent is started. There are
18 rejection subcases and three valid-dispatch subcases in two test methods.
This is a focused validation regression, not an exchange integration test or
permission to use the direct order path.

Existing local, unpushed GUI work includes a separate <= 0 guard. This change
does not duplicate that work and does not resolve other order-path concerns
such as instrument fallback or approval integration. Review before integration.
