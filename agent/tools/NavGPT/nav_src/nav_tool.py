"""Standalone NavGPT decision tool used by the InternS2 agent."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .llm_client import OpenAICompatibleChatClient


NAVGPT_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "navgpt_navigation",
        "description": (
            "Plan indoor navigation or select the next movement from a grounded visual "
            "observation. Use this for navigation requests. If the environment did not "
            "provide candidate viewpoint IDs, pass an empty list instead of inventing IDs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "instruction": {
                    "type": "string",
                    "description": "The user's navigation goal or route instruction.",
                },
                "observation": {
                    "type": "string",
                    "description": (
                        "A grounded description of visible scene geometry, landmarks, "
                        "obstacles, openings, and directional cues from the input image."
                    ),
                },
                "navigable_viewpoints": {
                    "type": "array",
                    "description": (
                        "Candidates supplied by the simulator/environment. Use [] when no "
                        "real candidate IDs are available."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "direction": {"type": "string"},
                            "distance": {"type": "number"},
                            "description": {"type": "string"},
                        },
                        "required": ["id"],
                    },
                },
                "history": {
                    "type": "string",
                    "description": "Optional concise history of earlier navigation steps.",
                },
            },
            "required": ["instruction", "observation", "navigable_viewpoints"],
        },
    },
}


SYSTEM_PROMPT = """You are NavGPT, an indoor vision-and-language navigation planner.
Use only the supplied observation, instruction, history, and candidates. Do not invent
viewpoint IDs or claim that an unseen area is safe. Decide whether to move, stop, or ask
for more environmental information. Return one concise JSON object with exactly these
fields:
{
  "status": "move" | "stop" | "need_more_information",
  "next_viewpoint_id": "an exact supplied candidate id or null",
  "direction": "an image-relative movement direction or empty string",
  "action": "a short executable navigation instruction",
  "reason": "a short evidence-based explanation",
  "action_plan": ["ordered short step", "..."]
}
If candidate IDs are supplied and status is move, next_viewpoint_id must exactly match
one of them. If no candidates are supplied, next_viewpoint_id must be null and direction
may contain a cautious image-relative recommendation. JSON output only.
"""


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Expected a boolean value, got {value!r}")


def _load_project_env(env_file: str | Path | None = None) -> None:
    try:
        from dotenv import load_dotenv
    except ImportError as exc:  # pragma: no cover - deployment dependent
        raise RuntimeError(
            "python-dotenv is not installed; run `pip install -r agent/requirements.txt`"
        ) from exc
    project_root = Path(__file__).resolve().parents[4]
    path = Path(env_file).expanduser().resolve() if env_file else project_root / ".env"
    load_dotenv(path, override=False)


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL | re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1).strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError(f"NavGPT did not return JSON: {text[:300]!r}") from None
        try:
            value = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"NavGPT returned invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("NavGPT JSON response must be an object")
    return value


class NavGPTTool:
    """Make one grounded navigation decision without requiring the R2R dataset."""

    def __init__(
        self,
        chat_client: OpenAICompatibleChatClient,
        *,
        json_mode: bool = True,
    ) -> None:
        self.chat_client = chat_client
        self.json_mode = json_mode

    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> "NavGPTTool":
        _load_project_env(env_file)
        try:
            timeout = float(os.getenv("DEEPSEEK_TIMEOUT", "120"))
            max_retries = int(os.getenv("DEEPSEEK_MAX_RETRIES", "2"))
            max_tokens = int(os.getenv("DEEPSEEK_MAX_TOKENS", "1200"))
            temperature = float(os.getenv("DEEPSEEK_TEMPERATURE", "0.0"))
        except ValueError as exc:
            raise ValueError(f"Invalid numeric DeepSeek setting: {exc}") from exc

        client = OpenAICompatibleChatClient(
            api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip(),
            model=os.getenv("DEEPSEEK_MODEL", "").strip(),
            timeout=timeout,
            max_retries=max_retries,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return cls(
            client,
            json_mode=_as_bool(os.getenv("NAVGPT_JSON_MODE"), True),
        )

    @staticmethod
    def _normalize_candidates(candidates: Any) -> list[dict[str, Any]]:
        if candidates is None:
            return []
        if not isinstance(candidates, list):
            raise ValueError("navigable_viewpoints must be a list")
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, candidate in enumerate(candidates):
            if not isinstance(candidate, dict):
                raise ValueError(f"navigable_viewpoints[{index}] must be an object")
            candidate_id = str(candidate.get("id", "")).strip()
            if not candidate_id:
                raise ValueError(f"navigable_viewpoints[{index}].id cannot be empty")
            if candidate_id in seen:
                raise ValueError(f"Duplicate candidate viewpoint id: {candidate_id}")
            seen.add(candidate_id)
            item: dict[str, Any] = {"id": candidate_id}
            for key in ("direction", "description"):
                if candidate.get(key) is not None:
                    item[key] = str(candidate[key]).strip()
            if candidate.get("distance") is not None:
                try:
                    item["distance"] = float(candidate["distance"])
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"navigable_viewpoints[{index}].distance must be numeric"
                    ) from exc
            normalized.append(item)
        return normalized

    @staticmethod
    def _validate_decision(
        decision: dict[str, Any], candidate_ids: set[str]
    ) -> dict[str, Any]:
        required = {"status", "next_viewpoint_id", "direction", "action", "reason", "action_plan"}
        missing = required.difference(decision)
        if missing:
            raise ValueError(f"NavGPT response is missing fields: {sorted(missing)}")

        status = decision["status"]
        if status not in {"move", "stop", "need_more_information"}:
            raise ValueError(f"Invalid NavGPT status: {status!r}")
        next_id = decision["next_viewpoint_id"]
        if next_id is not None:
            next_id = str(next_id).strip()
            decision["next_viewpoint_id"] = next_id or None

        if status != "move" and decision["next_viewpoint_id"] is not None:
            raise ValueError(f"NavGPT status {status!r} must use a null next_viewpoint_id")
        if status == "move" and candidate_ids:
            if decision["next_viewpoint_id"] not in candidate_ids:
                raise ValueError(
                    "NavGPT selected an unknown viewpoint ID: "
                    f"{decision['next_viewpoint_id']!r}; valid IDs are {sorted(candidate_ids)}"
                )
        elif status == "move" and not candidate_ids and decision["next_viewpoint_id"] is not None:
            raise ValueError("NavGPT invented a viewpoint ID when no candidates were supplied")

        if not isinstance(decision["action_plan"], list) or not all(
            isinstance(step, str) for step in decision["action_plan"]
        ):
            raise ValueError("NavGPT action_plan must be a list of strings")
        for key in ("direction", "action", "reason"):
            if not isinstance(decision[key], str):
                raise ValueError(f"NavGPT field {key!r} must be a string")
            decision[key] = decision[key].strip()
        if status == "move" and not candidate_ids and not decision["direction"]:
            raise ValueError("NavGPT must provide a direction when moving without candidate IDs")
        return decision

    def navigate(
        self,
        instruction: str,
        observation: str,
        navigable_viewpoints: list[dict[str, Any]] | None,
        history: str = "",
    ) -> dict[str, Any]:
        instruction = str(instruction).strip()
        observation = str(observation).strip()
        history = str(history or "").strip()
        if not instruction:
            raise ValueError("instruction cannot be empty")
        if not observation:
            raise ValueError("observation cannot be empty")

        candidates = self._normalize_candidates(navigable_viewpoints)
        candidate_ids = {item["id"] for item in candidates}
        request = {
            "instruction": instruction,
            "observation": observation,
            "history": history or "No previous navigation steps.",
            "navigable_viewpoints": candidates,
        }
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": "Navigation input (produce JSON):\n"
                + json.dumps(request, ensure_ascii=False, indent=2),
            },
        ]

        last_error: ValueError | None = None
        for attempt in range(2):
            raw = self.chat_client.chat(messages, json_mode=self.json_mode)
            try:
                decision = self._validate_decision(_extract_json(raw), candidate_ids)
            except ValueError as exc:
                last_error = exc
                if attempt == 1:
                    break
                messages.extend(
                    [
                        {"role": "assistant", "content": raw},
                        {
                            "role": "user",
                            "content": (
                                f"The previous JSON is invalid: {exc}. Correct it using only "
                                f"these candidate IDs: {sorted(candidate_ids)}. JSON only."
                            ),
                        },
                    ]
                )
                continue

            return {
                "decision": decision,
                "candidate_ids": sorted(candidate_ids),
                "provider_model": self.chat_client.model,
            }

        raise ValueError(f"NavGPT could not produce a valid decision: {last_error}")
