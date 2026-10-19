"""Image policy gateway: in front of ComfyUI, every queued job is classified before it is forwarded.

The nginx relay sends it only the job submission addresses (/prompt and /api/prompt); everything
else (images, history, web socket, interface) goes straight to ComfyUI. Standard library only.
"""
import json
import os
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = os.environ.get("COMFYUI_UPSTREAM", "http://host.docker.internal:8090")  # ComfyUI
HOST = os.environ.get("COMFYUI_HOST", "comfyui.localhost")
OWUI = os.environ.get("OWUI_INTERNAL", "http://open-webui.terminals.svc.cluster.local:8080")
MODEL = os.environ.get("CHARTER_MODEL", "gpt-5.6-luna")
REFUSAL = os.environ.get("REFUSAL_MESSAGE", "Request refused by the Example Company image policy")
TEXT_FIELDS = {"text", "string_a", "string_b", "prompt"}
CHARTER = open(os.environ.get("CHARTER", "/charter/charter.md"), encoding="utf-8").read()
token = {"value": None}


def texts(workflow: dict):
    """Every text field of the workflow, whatever the node (links, which are lists, are skipped)."""
    for node in workflow.values():
        for key, value in (node.get("inputs") or {}).items():
            if key in TEXT_FIELDS and isinstance(value, str) and value.strip():
                yield value.strip()


def call(url: str, body: dict, headers: dict = None) -> dict:
    """JSON POST to Open WebUI, JSON answer."""
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(request, timeout=60) as r:
        return json.loads(r.read())


def sign_in() -> None:
    """Token of the "Image policy" robot account (user role in Open WebUI)."""
    r = call(f"{OWUI}/api/v1/auths/signin", {"email": os.environ["ROBOT_EMAIL"], "password": os.environ["ROBOT_PASSWORD"]})
    token["value"] = r["token"]


def classify(text: str) -> dict:
    """Verdict of the instance's model, the policy as instructions, on behalf of the robot."""
    body = {"model": MODEL, "stream": False,
            "messages": [{"role": "system", "content": CHARTER}, {"role": "user", "content": text}]}
    for attempt in (1, 2):
        if not token["value"]:
            sign_in()
        try:
            r = call(f"{OWUI}/api/chat/completions", body, {"Authorization": f"Bearer {token['value']}"})
        except urllib.error.HTTPError as e:
            if e.code == 401 and attempt == 1:  # expired token: sign in again, once
                token["value"] = None
                continue
            raise
        content = r["choices"][0]["message"]["content"]
        return json.loads(content[content.find("{"): content.rfind("}") + 1])
    raise RuntimeError("robot sign-in refused")


def log(verdict: dict, fields: list) -> None:
    """One log line per refusal (read with kubectl logs): the beginning of each text field."""
    print(json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "category": verdict.get("categorie"),
                      "reason": verdict.get("motif"), "texts": [t[:90] for t in fields]}, ensure_ascii=False), flush=True)


class Gateway(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            job = json.loads(body or b"{}")
            fields = list(texts(job.get("prompt") or {}))
        except (ValueError, AttributeError):
            job, fields = None, []
        text = "\n".join(fields)
        try:
            verdict = classify(text) if text else {"verdict": "accepte"}
        except Exception as e:  # classification impossible: when in doubt, nothing goes through
            verdict = {"verdict": "refuse", "categorie": "unavailable", "motif": f"classification impossible ({e.__class__.__name__})"}
        if job is None or verdict.get("verdict") != "accepte":
            verdict.setdefault("motif", "unreadable request")
            log(verdict, fields)
            message = f"{REFUSAL}: {verdict.get('motif')}"
            error = {"error": {"type": "policy", "message": message, "details": message, "extra_info": {}}, "node_errors": {}}
            return self.answer(400, json.dumps(error, ensure_ascii=False).encode(), "application/json")
        self.forward(body)

    def do_GET(self):  # GET /prompt: queue status, forwarded as is
        self.forward(None)

    def forward(self, body):
        """An accepted request goes to ComfyUI unchanged; its answer comes back unchanged."""
        headers = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "content-length", "connection")}
        request = urllib.request.Request(f"{UPSTREAM}{self.path}", data=body, method=self.command, headers={**headers, "Host": HOST})
        try:
            with urllib.request.urlopen(request, timeout=120) as r:
                self.answer(r.status, r.read(), r.headers.get("Content-Type", "application/json"))
        except urllib.error.HTTPError as e:
            self.answer(e.code, e.read(), e.headers.get("Content-Type", "application/json"))

    def answer(self, status: int, content: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, *args):  # no access log: refusals only
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8189), Gateway).serve_forever()
