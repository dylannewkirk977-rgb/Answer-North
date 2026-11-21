"""Minimal Ollama client (native API, standard library only).

We use Ollama's native /api/chat instead of the OpenAI-compatible endpoint because
it lets us set the context size (num_ctx) and force a JSON schema for the reply.
"""
import json
import urllib.error
import urllib.request


def chat_json(llm_cfg: dict, messages: list[dict], schema: dict) -> dict:
    """Send a chat request and return the model's reply parsed as JSON."""
    body = {
        "model": llm_cfg["model"],
        "messages": messages,
        "stream": False,
        "think": bool(llm_cfg.get("think", False)),
        "format": schema,
        "options": {
            "num_ctx": int(llm_cfg.get("context_tokens", 16384)),
            "temperature": float(llm_cfg.get("temperature", 0.3)),
        },
    }
    url = llm_cfg["base_url"].rstrip("/") + "/api/chat"
    req = urllib.request.Request(
        url, json.dumps(body).encode("utf-8"), {"Content-Type": "application/json"}
    )

    last_error = None
    for _attempt in range(2):  # one retry if the reply isn't valid JSON
        try:
            with urllib.request.urlopen(req, timeout=llm_cfg.get("timeout_seconds", 600)) as resp:
                reply = json.load(resp)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            if e.code == 404 and "not found" in detail:
                raise RuntimeError(
                    f"Ollama model '{llm_cfg['model']}' isn't downloaded. "
                    f"Run: ollama pull {llm_cfg['model']}"
                ) from e
            raise RuntimeError(f"Ollama error {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"Can't reach Ollama at {llm_cfg['base_url']}. Is the Ollama app running?"
            ) from e

        try:
            return json.loads(reply["message"]["content"])
        except (KeyError, json.JSONDecodeError) as e:
            last_error = e
    raise RuntimeError(f"Model returned invalid JSON twice: {last_error}")
