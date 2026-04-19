"""
Shared types for document parsers.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class ChunkType(Enum):
    TEXT = "TEXT"
    IMAGE = "IMAGE"
    TABLE = "TABLE"


@dataclass
class Image:
    type: Literal["image_data_uri", "image_path", "no_image"] = "no_image"
    data_uri: str = ""
    path: str = ""


@dataclass
class Metadata:
    is_title: bool = False
    title_level: int = -1


@dataclass
class Chunk:
    type: str = ChunkType.TEXT.value
    text: str = ""
    image: Image = field(default_factory=Image)
    metadata: Metadata = field(default_factory=Metadata)
