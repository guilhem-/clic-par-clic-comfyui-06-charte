"""
title: Image policy
author: Example Company
description: Refuses, before the model, image requests that go against the Example Company image policy.
version: 1.0.0
licence: MIT
"""

import json

from pydantic import BaseModel, Field

from open_webui.models.users import UserModel
from open_webui.utils.chat import generate_chat_completion

# The organization's image policy: one single text, the same for the filter, the tool and the gateway.
CHARTER = """Du klassifizierst Bildbeschreibungen für die Beispielorganisation. Lehne eine Beschreibung ab, wenn sie Folgendes verlangt:
- eine erkennbare reale Person (namentlich genannt oder eindeutig bezeichnet);
- das Logo, die Marke oder ein erkennbares Produkt eines Dritten;
- gewalttätige, hasserfüllte oder sexuelle Inhalte;
- ein politisches Thema (Partei, Wahl, politische Persönlichkeit, Slogan).
Beurteile nur den erhaltenen Text, ohne Kontext anzunehmen: eine fiktive, anonyme oder allgemein beschriebene Person ist erlaubt. Die Stilvorgaben der Organisation (Farben, Formen, „keine Marke, kein Text“) sind nie ein Ablehnungsgrund.
Antworte nur mit einem JSON-Objekt: {"verdict": "accepte" oder "refuse", "categorie": "personne", "marque", "violence", "haine", "sexuel", "politique" oder "aucune", "motif": ein kurzer Satz auf Deutsch}."""


class Filter:
    class Valves(BaseModel):
        model: str = Field(
            default="gpt-5.6-luna",
            description="Model of the instance that classifies requests",
        )

    def __init__(self):
        self.valves = self.Valves()

    async def inlet(
        self, body: dict, __user__: dict, __request__=None, __event_emitter__=None
    ) -> dict:
        # 1. Only image requests are classified: Image switch turned on.
        if not (body.get("features") or {}).get("image_generation"):
            return body

        # 2. The user's last message, as they wrote it.
        message = next(
            (m["content"] for m in reversed(body["messages"]) if m["role"] == "user"),
            "",
        )
        if isinstance(message, list):  # message with an attached image
            message = " ".join(p.get("text", "") for p in message)

        # 3. The classification model's verdict, the policy as instructions.
        verdict = await self._classify(__request__, UserModel(**__user__), message)

        # 4. Against the policy: the request stops here, reason shown.
        if verdict.get("verdict") != "accepte":
            raise Exception(
                "Anfrage von der Bildrichtlinie der Beispielorganisation abgelehnt: "
                f"{verdict.get('motif')}"
            )

        # 5. Compliant: we say so, and the request goes on to the model.
        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {"description": "Richtlinie: konform", "done": True},
                }
            )
        return body

    async def _classify(self, request, user: UserModel, text: str) -> dict:
        """One call to the instance's model; an unreadable answer is refused."""
        response = await generate_chat_completion(
            request,
            {
                "model": self.valves.model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": CHARTER},
                    {"role": "user", "content": text},
                ],
            },
            user,
        )
        if not isinstance(response, dict):  # an HTTP response rather than a dictionary
            response = json.loads(response.body)
        content = response["choices"][0]["message"]["content"]
        try:
            return json.loads(content[content.find("{") : content.rfind("}") + 1])
        except ValueError:
            return {
                "verdict": "refuse",
                "motif": "Einstufung unlesbar, vorsichtshalber abgelehnt",
            }
