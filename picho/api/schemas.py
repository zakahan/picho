from pydantic import BaseModel
from typing import Literal, Union


class CreateSessionRequest(BaseModel):
    session_id: str | None = None


class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ImageBase64Part(BaseModel):
    type: Literal["image_base64"] = "image_base64"
    data: str
    mime_type: str = "image/png"


class ImageUrlPart(BaseModel):
    type: Literal["image_url"] = "image_url"
    url: str


Part = Union[TextPart, ImageBase64Part, ImageUrlPart]


class RequestMessage(BaseModel):
    role: Literal["user"] = "user"
    content: str | list[Part]


class RunRequest(BaseModel):
    session_id: str
    streaming: bool = False
    message: RequestMessage
