"""Install the image policy in Open WebUI, through its API: the filter and the tool, version 2.

Does what module 6 of the "Image generation in Open WebUI with ComfyUI" series does on screen:
  1. creates (or updates) the "Image policy" filter function (open-webui/image_charter.py),
     turns it on and makes it global: it applies to every model;
  2. replaces the code of the "Image workshop" tool with version 2 (open-webui/image_workshop.py),
     which has the description written by the model classified before any image is computed;
  3. sets the classification model in both valves (CHARTER_MODEL);
  4. creates (or resets) the "Image policy" robot account used by the gateway (role "user"),
     and prints the kubectl commands that hand its credentials to the gateway.
The third place, the gateway in front of ComfyUI, is deployed with kubectl (see README).

Usage:
  python setup_charter.py            # filter, tool version 2, robot account
  python setup_charter.py --check    # what is in place, and a classification test as the robot
  python setup_charter.py --undo     # filter deleted, tool back to version 1 (if found), robot deleted

Settings: .env file (see .env.example); environment variables take precedence.
LANGUAGE=de installs the German variants (open-webui/*.de.py, charter.de.md): same code, German
policy, status and refusal messages, as shown in the German video.
No dependency: Python 3.10 or newer, standard library only.
"""
import json
import os
import pathlib
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
FILTER_CODE = HERE / "open-webui" / "image_charter.py"
TOOL_CODE = HERE / "open-webui" / "image_workshop.py"
CHARTER = HERE / "charter.md"
VARIABLES = ("OWUI_URL", "OWUI_TOKEN", "TOOL_ID", "CHARTER_MODEL", "ROBOT_EMAIL", "ROBOT_PASSWORD", "TOOL_V1", "LANGUAGE")
FILTER = {"id": "image_policy", "name": "Image policy"}


def settings() -> dict:
    """Defaults, then .env (key=value), then the environment, which wins."""
    s = {
        "OWUI_URL": "http://127.0.0.1:8080", "TOOL_ID": "image_workshop", "CHARTER_MODEL": "gpt-5.6-luna",
        "ROBOT_EMAIL": "image-policy@example.com", "LANGUAGE": "en",
    }
    env = HERE / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                s[key.strip()] = value.strip()
    for key in VARIABLES:
        if os.environ.get(key):
            s[key] = os.environ[key]
    return s


S = settings()

# German variants: same code and blocks, the texts read by the user and by the classifier in German.
if S["LANGUAGE"].lower() == "de":
    FILTER_CODE = HERE / "open-webui" / "image_charter.de.py"
    TOOL_CODE = HERE / "open-webui" / "image_workshop.de.py"
    CHARTER = HERE / "charter.de.md"
    FILTER["name"] = "Bildrichtlinie"
elif S["LANGUAGE"].lower() != "en":
    sys.exit(f"LANGUAGE={S['LANGUAGE']}: en or de.")


def api(method: str, path: str, body=None, tolerate=False, token=None):
    """Call Open WebUI's API, with an administrator token by default."""
    token = token or S.get("OWUI_TOKEN")
    if not token:
        sys.exit("OWUI_TOKEN missing (.env): token of an Open WebUI administrator account.")
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        S["OWUI_URL"].rstrip("/") + path, data=data, method=method,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            text = resp.read().decode()
    except urllib.error.HTTPError as e:
        if tolerate:
            return None
        sys.exit(f"{method} {path}: {e.code} {e.read().decode()[:300]}")
    return json.loads(text) if text.strip() else None


def install_filter() -> None:
    code = FILTER_CODE.read_text(encoding="utf-8")
    if api("GET", f"/api/v1/functions/id/{FILTER['id']}", tolerate=True):
        api("POST", f"/api/v1/functions/id/{FILTER['id']}/update",
            {"id": FILTER["id"], "name": FILTER["name"], "content": code, "meta": {"description": "", "manifest": {}}})
    else:
        api("POST", "/api/v1/functions/create",
            {"id": FILTER["id"], "name": FILTER["name"], "content": code, "meta": {"description": "", "manifest": {}}})
    f = api("GET", f"/api/v1/functions/id/{FILTER['id']}")
    if not f.get("is_active"):
        api("POST", f"/api/v1/functions/id/{FILTER['id']}/toggle")
    if not f.get("is_global"):
        api("POST", f"/api/v1/functions/id/{FILTER['id']}/toggle/global")
    api("POST", f"/api/v1/functions/id/{FILTER['id']}/valves/update", {"model": S["CHARTER_MODEL"]})
    print(f"Filter {FILTER['id']}: on, global, model {S['CHARTER_MODEL']}")


def update_tool() -> None:
    tool = api("GET", f"/api/v1/tools/id/{S['TOOL_ID']}", tolerate=True)
    if not tool:
        sys.exit(f"Tool {S['TOOL_ID']} not found: install module 4's Image workshop first.")
    backup = HERE / "tool-v1.backup.py"
    if "charter" not in tool["content"].lower() and not backup.exists():
        backup.write_text(tool["content"], encoding="utf-8")
    api("POST", f"/api/v1/tools/id/{S['TOOL_ID']}/update", {
        "id": S["TOOL_ID"], "name": tool["name"], "content": TOOL_CODE.read_text(encoding="utf-8"),
        "meta": tool["meta"], "access_grants": tool.get("access_grants", []),
    })
    valves = api("GET", f"/api/v1/tools/id/{S['TOOL_ID']}/valves") or {}
    api("POST", f"/api/v1/tools/id/{S['TOOL_ID']}/valves/update", {**valves, "charter_model": S["CHARTER_MODEL"]})
    print(f"Tool {S['TOOL_ID']}: version 2 (image policy check), model {S['CHARTER_MODEL']}")


def find_robot():
    users = api("GET", f"/api/v1/users/?query={urllib.parse.quote(S['ROBOT_EMAIL'])}").get("users", [])
    return next((u for u in users if u["email"] == S["ROBOT_EMAIL"] and u["role"] != "admin"), None)


def install_robot() -> None:
    password = S.get("ROBOT_PASSWORD") or secrets.token_hex(24) + "A1"
    robot = find_robot()
    if robot:
        api("POST", f"/api/v1/users/{robot['id']}/update", {"role": "user", "name": "Image policy", "email": S["ROBOT_EMAIL"],
                                                              "profile_image_url": robot.get("profile_image_url") or "/user.png", "password": password})
    else:
        api("POST", "/api/v1/auths/add", {"name": "Image policy", "email": S["ROBOT_EMAIL"], "password": password, "role": "user"})
    print(f"Robot {S['ROBOT_EMAIL']} ready (role user). Hand it to the gateway, without echoing the password:")
    print("  kubectl create secret generic comfyui-gateway -n comfyui \\")
    print(f"    --from-literal=ROBOT_EMAIL={S['ROBOT_EMAIL']} --from-literal=ROBOT_PASSWORD=\"$ROBOT_PASSWORD\"")
    if not S.get("ROBOT_PASSWORD"):
        (HERE / ".robot-password").write_text(password, encoding="utf-8")
        print("  (generated password written to .robot-password, git-ignored: export ROBOT_PASSWORD=$(cat .robot-password))")


TEST_REQUEST = ("Das Coca-Cola-Logo auf einer Dose, Produktfoto." if S["LANGUAGE"].lower() == "de"
                else "The Coca-Cola logo on a can, product photo.")


def check() -> None:
    f = api("GET", f"/api/v1/functions/id/{FILTER['id']}", tolerate=True)
    print(f"Filter: {'on' if f and f['is_active'] else 'off'}, {'global' if f and f['is_global'] else 'not global'}" if f else "Filter: absent")
    t = api("GET", f"/api/v1/tools/id/{S['TOOL_ID']}", tolerate=True)
    print(f"Tool: {'version 2' if t and '_classify' in t['content'] else 'version 1 or absent'}")
    print(f"Robot: {'present' if find_robot() else 'absent'}")
    if S.get("ROBOT_PASSWORD"):
        r = urllib.request.Request(S["OWUI_URL"].rstrip("/") + "/api/v1/auths/signin", method="POST",
                                   data=json.dumps({"email": S["ROBOT_EMAIL"], "password": S["ROBOT_PASSWORD"]}).encode(),
                                   headers={"Content-Type": "application/json"})
        token = json.loads(urllib.request.urlopen(r, timeout=30).read())["token"]
        answer = api("POST", "/api/chat/completions", {"model": S["CHARTER_MODEL"], "stream": False, "messages": [
            {"role": "system", "content": CHARTER.read_text(encoding="utf-8")},
            {"role": "user", "content": TEST_REQUEST}]}, token=token)
        print(f"Classification as the robot: {answer['choices'][0]['message']['content']}")


def undo() -> None:
    api("DELETE", f"/api/v1/functions/id/{FILTER['id']}/delete", tolerate=True)
    backup = HERE / "tool-v1.backup.py"
    tool = api("GET", f"/api/v1/tools/id/{S['TOOL_ID']}", tolerate=True)
    if tool and backup.exists():
        api("POST", f"/api/v1/tools/id/{S['TOOL_ID']}/update", {"id": S["TOOL_ID"], "name": tool["name"],
            "content": backup.read_text(encoding="utf-8"), "meta": tool["meta"], "access_grants": tool.get("access_grants", [])})
    robot = find_robot()
    if robot:
        api("DELETE", f"/api/v1/users/{robot['id']}")
    print("Filter deleted, tool back to version 1" + (" (backup)" if backup.exists() else " (no backup: unchanged)") + ", robot deleted.")


if __name__ == "__main__":
    if "--check" in sys.argv:
        check()
    elif "--undo" in sys.argv:
        undo()
    else:
        install_filter()
        update_tool()
        install_robot()
