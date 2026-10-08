#!/usr/bin/env bash

# Shared InternS2 endpoint configuration for the service launchers.  This file
# is sourced; it must not enable shell options or start a process by itself.

interns2_configure() {
    local app_root="$1"
    local mode="${INTERNS2_INFERENCE_MODE:-local}"
    local base_url
    local api_key="${INTERNS2_API_KEY:-}"
    local api_key_file="${INTERNS2_API_KEY_FILE:-}"

    case "$mode" in
        local)
            base_url="http://127.0.0.1:23333/v1"
            api_key="EMPTY"
            ;;
        api)
            # These are the deployed service defaults. Operators only need to
            # select api mode; each value can still be overridden if the
            # service is moved later.
            base_url="${INTERNS2_BASE_URL:-http://127.0.0.1:23333/v1}"
            if [[ -z "$api_key" && -z "$api_key_file" ]]; then
                api_key_file="$app_root/configs/interns2-api-key.local"
            fi
            export INTERNS2_MODEL="${INTERNS2_MODEL:-interns2-medlora}"
            base_url="${base_url%/}"
            case "$base_url" in
                http://*/v1|https://*/v1) ;;
                *)
                    echo "ERROR: INTERNS2_BASE_URL must be an http(s) OpenAI-compatible /v1 URL." >&2
                    return 1
                    ;;
            esac

            if [[ -n "$api_key_file" ]]; then
                if [[ -n "$api_key" && "$api_key" != "EMPTY" ]]; then
                    echo "ERROR: set only one of INTERNS2_API_KEY or INTERNS2_API_KEY_FILE." >&2
                    return 1
                fi
                if [[ "$api_key_file" != /* ]]; then
                    api_key_file="$app_root/$api_key_file"
                fi
                [[ -f "$api_key_file" && -r "$api_key_file" ]] || {
                    echo "ERROR: InternS2 API key file is missing or unreadable: $api_key_file" >&2
                    return 1
                }
                api_key="$(tr -d '\r\n' < "$api_key_file")"
            fi
            [[ -n "$api_key" && "$api_key" != "EMPTY" ]] || {
                echo "ERROR: api inference mode requires a non-empty API key." >&2
                return 1
            }
            ;;
        *)
            echo "ERROR: INTERNS2_INFERENCE_MODE must be local or api." >&2
            return 1
            ;;
    esac

    export INTERNS2_INFERENCE_MODE="$mode"
    export INTERNS2_BASE_URL="$base_url"
    export INTERNS2_API_KEY="$api_key"
    # Child Python processes receive the resolved secret through one source,
    # avoiding ambiguity with AgentSettings' direct key-file support.
    unset INTERNS2_API_KEY_FILE
}
