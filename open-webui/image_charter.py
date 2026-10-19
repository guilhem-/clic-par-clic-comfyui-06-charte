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
CHARTER = """You classify image descriptions for the Example Company. Refuse a description if it asks for:
- an identifiable real person (named, or designated unambiguously);
- the logo, brand or recognizable product of a third-party company;
- violent, hateful or sexual content;
- a political subject (party, election, political figure, slogan).
Judge only the text you receive, without assuming any context: a fictional, anonymous or generically described person is accepted. The organization's style instructions (colors, shapes, "no brand, no text") are never a reason to refuse.
Answer only with a JSON object: {"verdict": "accepte" or "refuse", "categorie": "personne", "marque", "violence", "haine", "sexuel", "politique" or "aucune", "motif": one short sentence in English}."""


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
                "Request refused by the Example Company image policy: "
                f"{verdict.get('motif')}"
            )

        # 5. Compliant: we say so, and the request goes on to the model.
        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {"description": "Policy: message compliant", "done": True},
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
                "motif": "unreadable classification, refused to be safe",
            }
