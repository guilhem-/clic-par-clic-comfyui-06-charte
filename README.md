# What may be generated? — an image policy for Open WebUI and ComfyUI

Demo code for module 6 of the "Click by Click" series **Image generation in Open WebUI with
ComfyUI**. The organization has an image policy (no identifiable real person, no third-party
logo or brand, no violent, hateful or sexual content, no political subject). A language model of
the instance classifies each description against it. The question of the module is **where** to
check: there are three places, and only one of them sees every request.

Video: {{video}}

## Three places to check

| Place | What it sees | What the user sees when it refuses |
|---|---|---|
| **1. A filter function of Open WebUI** (`open-webui/image_charter.py`) | The user's last message, once, before the chat model (`inlet`). Not the description the model writes afterwards for the image tool, and nothing from the API (`/api/v1/images/generations`) or from ComfyUI's interface. | A clear error with the reason, right away |
| **2. The custom tool** "Image workshop", version 2 (`open-webui/image_workshop.py`) | The final description written by the model, before any image is computed. Only for this tool. | A clear refusal, explained by the model |
| **3. A gateway in front of ComfyUI** (`gateway/gateway.py`) | Every job submitted to ComfyUI's queue (`POST /prompt`, `/api/prompt`): chats, API, ComfyUI's own interface. | In ComfyUI's interface: the reason. In Open WebUI: only a failure (its ComfyUI client does not read the error body); the reason is in the gateway's log |

The video shows the trap: "Who formulated the theory of relativity?", then "Make a realistic
portrait of him for the conference poster". The last message names nobody: the filter lets it
through. The description written by the model names the physicist: the gateway refuses it.

| File | Content |
|---|---|
| `charter.md` | The image policy: one single text, the classification instructions (JSON verdict) |
| `open-webui/image_charter.py` | Filter function (`inlet`), shown in the English and German videos; the French video shows its French version, `charte_images.py` (same structure, same blocks) |
| `open-webui/image_workshop.py` | The "Image workshop" tool of modules 4 and 5, **version 2**: block 2 has the description classified (`_classify`) and returns a refusal sentence to the model |
| `open-webui/workshop-instructions.txt` | System prompt of the "Image workshop" model (module 4) |
| `charter.de.md`, `open-webui/image_charter.de.py`, `open-webui/image_workshop.de.py`, `open-webui/workshop-instructions.de.txt` | German variants shown in the German video: same code and blocks, policy, status and refusal messages in German (`LANGUAGE=de`) |
| `gateway/gateway.py` | The gateway: reads every text field of the workflow, has them classified by Open WebUI's chat API on behalf of a robot account, refuses when in doubt, logs each refusal, forwards accepted jobs unchanged. Python standard library only |
| `comfyui/k8s-relay-gateway.yaml` | The relay (nginx) with the gateway as a second container: only `/prompt` and `/api/prompt` go to the gateway, everything else (images, history, web socket) goes straight to ComfyUI |
| `comfyui/k8s-relay.yaml` | The relay alone (modules 1 to 5), to go back |
| `setup_charter.py` | Filter (on, global), tool version 2, robot account, through Open WebUI's API; `--check`, `--undo` |
| `test/requests.sh` | Two jobs sent straight to ComfyUI's API through the gateway: a landscape (200) and a logo (400) |

## Prerequisites

- The image server of modules 1 and 2 (ComfyUI v0.41 on a GPU, connected to Open WebUI 0.11) —
  [`clic-par-clic-comfyui-01-brancher`](https://github.com/guilhem-/clic-par-clic-comfyui-01-brancher),
  [`clic-par-clic-comfyui-02-workflow-organisation`](https://github.com/guilhem-/clic-par-clic-comfyui-02-workflow-organisation).
- The "Image workshop" tool and model of modules 4 and 5 —
  [`clic-par-clic-comfyui-05-droits-groupes`](https://github.com/guilhem-/clic-par-clic-comfyui-05-droits-groupes)
  (`python setup_permissions.py --install-workshop`).
- Functions enabled in Open WebUI (`ENABLE_PLUGINS`, on by default), an **administrator** account,
  and a chat model readable by every user (here `gpt-5.6-luna`): the filter and the tool classify on
  behalf of the user, the gateway on behalf of the robot.
- For the gateway: the ComfyUI relay in a Kubernetes cluster (the series uses k3d), `kubectl`.
- Python 3.10+ (standard library only); `curl` and `bash` for the test.

## Step by step

### 1. Filter and tool, in Open WebUI

By hand, as in the video:

1. **Admin Panel › Functions › New function**: name `Image policy`, id `image_policy`, paste
   `open-webui/image_charter.py`, **Save & Create**. In the list, turn it **on**, then in its menu
   switch **Global** on: it now applies to every model.
2. **Workspace › Tools › Image workshop**: replace the code with `open-webui/image_workshop.py`
   (version 2), **Save**.

**German version** (as in the German video): name `Bildrichtlinie`, id `image_policy`, paste
`open-webui/image_charter.de.py`, then `open-webui/image_workshop.de.py` for the tool, and give the
"Image workshop" model `open-webui/workshop-instructions.de.txt` as its system prompt. Same code
and blocks; only the policy, the status and the refusal messages are German.

Or through the API:

```bash
cp .env.example .env              # OWUI_URL, OWUI_TOKEN (administrator), TOOL_ID, CHARTER_MODEL
python setup_charter.py           # filter (on, global), tool version 2, robot account
python setup_charter.py --check   # what is in place (and a classification as the robot)
LANGUAGE=de python setup_charter.py   # German variants (or LANGUAGE=de in .env)
```

### 2. The gateway, in front of ComfyUI

```bash
kubectl apply -f comfyui/k8s-relay.yaml          # only if the relay is not there yet (Service and Ingress)
export ROBOT_EMAIL=image-policy@example.com
export ROBOT_PASSWORD=$(cat .robot-password)     # written by setup_charter.py (or your own)
kubectl create configmap comfyui-gateway -n comfyui \
  --from-file=gateway.py=gateway/gateway.py --from-file=charter.md=charter.md
kubectl create secret generic comfyui-gateway -n comfyui \
  --from-literal=ROBOT_EMAIL="$ROBOT_EMAIL" --from-literal=ROBOT_PASSWORD="$ROBOT_PASSWORD"
kubectl apply -f comfyui/k8s-relay-gateway.yaml
kubectl rollout status deployment/comfyui-relay -n comfyui
```

Adapt `COMFYUI_UPSTREAM`, `COMFYUI_HOST`, `OWUI_INTERNAL` and the two `proxy_pass` lines to your
setup. The refusal starts with "Request refused by the Example Company image policy"; for another
language, add `--from-literal=refusal-message="…"` to the ConfigMap (and have the policy ask for
the reason in that language). In German, as in the video:

```bash
kubectl create configmap comfyui-gateway -n comfyui \
  --from-file=gateway.py=gateway/gateway.py --from-file=charter.md=charter.de.md \
  --from-literal=refusal-message="Anfrage von der Bildrichtlinie der Beispielorganisation abgelehnt"
```

Back to the relay alone: `kubectl apply -f comfyui/k8s-relay.yaml`,
then delete the ConfigMap and the Secret.

## Try it

1. With a user account, **Image** on: "A realistic portrait of Albert Einstein for the Lyon
   conference poster." → the filter refuses, with the reason.
2. With the **Image workshop** model: "A thumbnail with the Coca-Cola logo for the summer party."
   → the tool refuses, the model explains; unfold the call to read the refusal sentence.
3. In ComfyUI's interface, type a brand logo in the text node and press **Run**: ComfyUI shows the
   gateway's refusal.
4. From the command line: `COMFYUI_URL=http://comfyui.localhost:8080 ./test/requests.sh`
   (landscape: HTTP 200; logo: HTTP 400).
5. The log of refusals: `kubectl logs deploy/comfyui-relay -c gateway -n comfyui`.

## Limits, honestly

- The gateway judges the **text**, not the image produced. Next step: have the image classified
  when Open WebUI downloads it, by a model that sees images.
- A classification model makes mistakes, in both directions; read the log with the communication
  team and adjust the policy. The policy says "judge only the text you receive": without it, a
  cautious model refuses every portrait.
- Each image costs one more call (one to two seconds), up to three with the filter and the tool.
- The rule only holds if ComfyUI is reachable **only** through the gateway (network policy: see
  [module 7](https://github.com/guilhem-/clic-par-clic-comfyui-07-exploitation)). In the series' set, ComfyUI is still reachable on the GPU machine directly.
- Confidentiality: descriptions go to the provider of the classification model, like the chats
  themselves.
- The JSON verdict keeps French keywords (`accepte`, `refuse`), shared by the three places and by
  the French version of the series.

## Series

- Previous module: **Who can generate images?** —
  [`clic-par-clic-comfyui-05-droits-groupes`](https://github.com/guilhem-/clic-par-clic-comfyui-05-droits-groupes).
- Next module: **Several users, one graphics card** —
  [`clic-par-clic-comfyui-07-exploitation`](https://github.com/guilhem-/clic-par-clic-comfyui-07-exploitation).

## License

MIT (see `LICENSE`). ComfyUI: GPL-3.0; Z-Image Turbo: Apache 2.0; Open WebUI: its own license
(the Open WebUI code quoted in the video stays theirs and is not copied here). Coca-Cola is a
trademark of its owner, quoted only as an example of what the policy refuses.
