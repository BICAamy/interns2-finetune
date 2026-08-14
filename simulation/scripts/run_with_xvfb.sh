#!/bin/sh

# Start one bounded Xvfb instance, wait until X clients can connect, then run
# the requested command. This avoids xvfb-run --auto-servernum retry loops and
# makes X server startup failures visible in container logs.

set -u

display_number="${XVFB_DISPLAY_NUMBER:-99}"
display=":${display_number}"
xvfb_log="${XVFB_LOG_FILE:-/tmp/xvfb-${display_number}.log}"
xvfb_pid=""
application_pid=""

cleanup() {
    if [ -n "${application_pid}" ] && kill -0 "${application_pid}" 2>/dev/null; then
        kill "${application_pid}" 2>/dev/null || true
        wait "${application_pid}" 2>/dev/null || true
    fi
    if [ -n "${xvfb_pid}" ] && kill -0 "${xvfb_pid}" 2>/dev/null; then
        kill "${xvfb_pid}" 2>/dev/null || true
        wait "${xvfb_pid}" 2>/dev/null || true
    fi
}

handle_signal() {
    signal_exit_code="$1"
    cleanup
    exit "${signal_exit_code}"
}

trap cleanup EXIT
trap 'handle_signal 129' HUP
trap 'handle_signal 130' INT
trap 'handle_signal 143' TERM

if [ "$#" -eq 0 ]; then
    echo "[step4-xvfb] no command supplied" >&2
    exit 64
fi

mkdir -p /tmp/.X11-unix
chmod 1777 /tmp/.X11-unix

echo "[step4-xvfb] starting Xvfb on ${display}" >&2
Xvfb "${display}" \
    -screen 0 1280x1024x24 \
    -nolisten tcp \
    -ac \
    >"${xvfb_log}" 2>&1 &
xvfb_pid="$!"

ready=0
attempt=0
while [ "${attempt}" -lt 150 ]; do
    if ! kill -0 "${xvfb_pid}" 2>/dev/null; then
        echo "[step4-xvfb] Xvfb exited before becoming ready" >&2
        cat "${xvfb_log}" >&2 || true
        exit 70
    fi

    if DISPLAY="${display}" xdpyinfo >/dev/null 2>&1; then
        ready=1
        break
    fi

    attempt=$((attempt + 1))
    sleep 0.1
done

if [ "${ready}" -ne 1 ]; then
    echo "[step4-xvfb] Xvfb was not ready after 15 seconds" >&2
    cat "${xvfb_log}" >&2 || true
    exit 70
fi

echo "[step4-xvfb] Xvfb is ready on ${display}" >&2
DISPLAY="${display}" "$@" &
application_pid="$!"
wait "${application_pid}"
application_status="$?"
application_pid=""
exit "${application_status}"

