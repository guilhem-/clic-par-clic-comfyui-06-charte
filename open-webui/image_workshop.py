"""
title: Image workshop
author: Example Company
description: Creates visuals in the Example Company formats (poster, banner, square) with the organization's image server, in line with its image policy.
version: 2.0.0
licence: MIT
"""

import json
from typing import Literal

from pydantic import BaseModel, Field

from open_webui.models.chats import Chats
from open_webui.models.users import UserModel
from open_webui.routers.images import (
    CreateImageForm,
    get_image_config,
    image_generations,
)
from open_webui.utils.access_control import has_permission
from open_webui.utils.chat import generate_chat_completion
from open_webui.utils.chat_id import is_saved_chat_id

# The organization's image policy: one single text, the same for the filter, the tool and the gateway.
CHARTER = """You classify image descriptions for the Example Company. Refuse a description if it asks for:
- an identifiable real person (named, or designated unambiguously);
- the logo, brand or recognizable product of a third-party company;
- violent, hateful or sexual content;
- a political subject (party, election, political figure, slogan).
Judge only the text you receive, without assuming any context: a fictional, anonymous or generically described person is accepted. The organization's style instructions (colors, shapes, "no brand, no text") are never a reason to refuse.
Answer only with a JSON object: {"verdict": "accepte" or "refuse", "categorie": "personne", "marque", "violence", "haine", "sexuel", "politique" or "aucune", "motif": one short sentence in English}."""

# Example Company formats, in pixels (width x height):
# multiples of 64, about one million pixels each.
FORMATS = {
    "poster": "832x1216",  # portrait, for print
    "banner": "1536x640",  # very wide, intranet header
    "square": "1024x1024",  # thumbnail, internal newsletter
}


class Tools:
    class Valves(BaseModel):
        max_variants: int = Field(
            default=1, ge=1, le=6, description="Maximum number of variants per request"
        )
        charter_model: str = Field(
            default="gpt-5.6-luna",
            description="Model of the instance that classifies descriptions",
        )

    def __init__(self):
        self.valves = self.Valves()

    async def create_visual(
        self,
        description: str,
        format: Literal["poster", "banner", "square"] = "square",
        variants: int = 1,
        __request__=None,
        __user__: dict = None,
        __event_emitter__=None,
        __chat_id__: str = None,
        __message_id__: str = None,
    ) -> str:
        """
        Creates one or more images with the organization's image server.
        :param description: the scene only (subject, setting, mood), in one or two sentences, without naming the use, always ending with "no text at all"; the style guide is added by the server
        :param format: poster (portrait, printed document), banner (very wide, intranet header) or square (thumbnail, internal newsletter)
        :param variants: number of different versions to offer, from 1 to 3
        """
        user = UserModel(**__user__)

        # 1. The right to generate images, checked like Open WebUI's public route does.
        if not await self._allowed(user):
            return "Refused: this account cannot generate images. Just say so."

        # 2. The image policy (module 6): the description written by the model, classified before any run.
        verdict = await self._classify(__request__, user, description)
        if verdict.get("verdict") != "accepte":
            await self._status(__event_emitter__, "Refused by the policy", done=True)
            return (
                "Refused by the Example Company image policy: "
                f"{verdict.get('motif')} Tell the user, without suggesting a workaround."
            )

        # 3. The number of variants, capped by the administrator's valve.
        n = max(1, min(int(variants), self.valves.max_variants))
        await self._status(__event_emitter__, f"{n} visual(s) in {format} format…")

        # 4. One variant = one full run of the workflow, with its own seed.
        size, images = FORMATS[format], []
        try:
            for _ in range(n):
                images += await self._generate(__request__, user, description, size)
        except Exception as error:
            await self._status(__event_emitter__, "Image server unavailable", done=True)
            return f"The image server failed ({error}). Tell the user."

        # 5. The images are attached to the message, then shown in the chat.
        files = [{"type": "image", **image} for image in images]
        if is_saved_chat_id(__chat_id__) and __message_id__:
            files = (
                await Chats.add_message_files_by_id_and_message_id(
                    __chat_id__, __message_id__, files
                )
                or files
            )
        if __event_emitter__:
            await __event_emitter__(
                {"type": "chat:message:files", "data": {"files": files}}
            )
        await self._status(__event_emitter__, "Visuals ready", done=True)

        # 6. The answer to the model: the images are already on screen, do not repeat them.
        return (
            f"{len(images)} image(s) in {format} format, already shown in the chat. "
            "Do not show them again and do not give a link: present them in one sentence."
        )

    async def _allowed(self, user: UserModel) -> bool:
        """Generation enabled on the Images page, and the "Image Generation" permission."""
        config = await get_image_config()
        if not config.ENABLE_IMAGE_GENERATION:
            return False
        return user.role == "admin" or await has_permission(
            user.id, "features.image_generation", config.USER_PERMISSIONS
        )

    async def _classify(self, request, user: UserModel, text: str) -> dict:
        """One call to the instance's model, the policy as instructions; unreadable: refused."""
        response = await generate_chat_completion(
            request,
            {
                "model": self.valves.charter_model,
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

    async def _generate(self, request, user, description: str, size: str) -> list:
        """One image: the workflow and node mapping of the Images page, at the format's size."""
        return await image_generations(
            request=request,
            form_data=CreateImageForm(prompt=description, size=size),
            user=user,
        )

    async def _status(self, emitter, text: str, done: bool = False) -> None:
        """Progress message shown above the answer."""
        if emitter:
            await emitter(
                {"type": "status", "data": {"description": text, "done": done}}
            )
