"""
PDF parser - converts PDF documents to chunks.
"""

import base64
import json
import os
import re
from io import BytesIO
from pathlib import Path

from picho.builtin.tool.extension.read.parser.types import (
    Chunk,
    ChunkType,
    Image,
    Metadata,
)


def parse_pdf(file_path: str, image_dir: str) -> list[Chunk]:
    """
    Parse a PDF file and return a list of chunks.

    Args:
        file_path: Path to the PDF file
        image_dir: Directory to save extracted images

    Returns:
        List of Chunk objects
    """
    import pymupdf
    from PIL import Image as PILImage

    result_list = []
    doc = pymupdf.open(file_path)

    Path(image_dir).mkdir(parents=True, exist_ok=True)
    image_counter = 0

    for page_idx in range(doc.page_count):
        page = doc[page_idx]
        dpi = 300
        page_image = PILImage.open(BytesIO(page.get_pixmap(dpi=dpi).tobytes()))
        width, height = page_image.size

        tables = pymupdf.table.find_tables(page).tables
        table_block_list = []
        for table in tables:
            table_block_list.append(
                {
                    "bbox": list(table.bbox),
                    "text": table.to_markdown(),
                }
            )

        page_dict = {
            "page_number": page_idx,
            "page_bbox": list(page.artbox),
            "chunks": [],
        }

        if height > width:
            fitz_page_dict = json.loads(page.get_text("json", sort=True))

            for block in fitz_page_dict["blocks"]:
                page_block = {"bbox": block["bbox"]}

                for table_block in table_block_list:
                    if _is_inside(table_block["bbox"], page_block["bbox"]):
                        if (
                            len(page_dict["chunks"]) == 0
                            or page_dict["chunks"][-1].get("type") != "TABLE"
                        ):
                            page_dict["chunks"].append(
                                {
                                    "type": "TABLE",
                                    "text": table_block["text"],
                                    "bbox": table_block["bbox"],
                                }
                            )
                        break
                else:
                    if "lines" in block:
                        page_block["type"] = "TEXT"
                        page_block_text_list = []
                        font_size = 24
                        for line in block["lines"]:
                            for span in line["spans"]:
                                page_block_text_list.append(span["text"])
                                if span["size"] < font_size:
                                    font_size = span["size"]
                        page_block["text"] = "".join(page_block_text_list)
                        page_block["text"] = _fullwidth_to_halfwidth(page_block["text"])
                        page_block["font_size"] = font_size
                        page_dict["chunks"].append(page_block)

                    elif "image" in block:
                        page_block["type"] = "IMAGE"
                        page_block["image"] = _get_page_image(page_image, block, dpi)
                        page_dict["chunks"].append(page_block)

        else:
            page_block = {
                "type": "IMAGE",
                "bbox": list(page.artbox),
                "image": _encode_image_to_base64(page_image),
            }
            page_dict["chunks"].append(page_block)

        current_text_blocks = []

        for block in page_dict["chunks"]:
            if block["type"] == "TEXT":
                if len(block["text"].strip()) == 0:
                    continue

                if _heading_check(block["text"], block.get("font_size", 12)):
                    if current_text_blocks:
                        current_chunks = _block_merge(current_text_blocks)
                        result_list.extend(current_chunks)
                        current_text_blocks = []

                    result_list.append(
                        Chunk(
                            type=ChunkType.TEXT.value,
                            text=block["text"].strip(),
                            image=Image(),
                            metadata=Metadata(is_title=True, title_level=1),
                        )
                    )
                else:
                    current_text_blocks.append(block)

            elif block["type"] == "IMAGE":
                if current_text_blocks:
                    current_chunks = _block_merge(current_text_blocks)
                    result_list.extend(current_chunks)
                    current_text_blocks = []

                image_filename = f"image_{image_counter}.png"
                image_path = os.path.join(image_dir, image_filename)
                _save_base64_image(block["image"], image_path)
                image_counter += 1

                result_list.append(
                    Chunk(
                        type=ChunkType.IMAGE.value,
                        text="",
                        image=Image(type="image_path", path=image_filename),
                    )
                )

            elif block["type"] == "TABLE":
                if current_text_blocks:
                    current_chunks = _block_merge(current_text_blocks)
                    result_list.extend(current_chunks)
                    current_text_blocks = []

                result_list.append(
                    Chunk(
                        type=ChunkType.TABLE.value,
                        text=block["text"],
                        image=Image(),
                    )
                )

        if current_text_blocks:
            current_chunks = _block_merge(current_text_blocks)
            result_list.extend(current_chunks)

    doc.close()
    return result_list


def _save_base64_image(base64_data: str, image_path: str) -> None:
    image_bytes = base64.b64decode(base64_data)
    with open(image_path, "wb") as f:
        f.write(image_bytes)


def _is_inside(rectA, rectB):
    A_x1, A_y1, A_x2, A_y2 = rectA
    B_x1, B_y1, B_x2, B_y2 = rectB
    return (A_x1 <= B_x1 and B_x2 <= A_x2) and (A_y1 <= B_y1 and B_y2 <= A_y2)


def _encode_image_to_base64(image) -> str:
    buffered = BytesIO()
    image.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode("utf-8")


def _get_page_image(image, block, dpi: int) -> str:
    r_box = tuple([b * dpi / 72 for b in block["bbox"]])
    image_clip = image.crop(r_box)
    buffered = BytesIO()
    image_clip.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode("utf-8")


def _fullwidth_to_halfwidth(s: str) -> str:
    result = []
    for char in s:
        if "\uff01" <= char <= "\uff5e":
            result.append(chr(ord(char) - 0xFEE0))
        else:
            result.append(char)
    return "".join(result)


def _heading_check(text: str, font_size: float) -> bool:
    font_size = font_size * 2
    max_heading_length = 15
    h1 = 48
    h2 = 36
    h3 = 28

    if _check_string_prefix(text):
        if font_size >= h2:
            return True
        elif h2 <= font_size <= h3 and len(text) < max_heading_length:
            return True
        else:
            return False
    else:
        if font_size >= h1:
            return True
        elif h1 <= font_size <= h2 and len(text) < max_heading_length:
            return True
        else:
            return False


def _check_string_prefix(s: str) -> bool:
    chinese_digits = "[一二三四五六七八九十百千万亿]"

    if re.match(f"^{chinese_digits}", s):
        return True
    if re.match(r"^\d", s):
        return True
    if re.match(r"^第\d", s):
        return True
    if re.match(f"^第{chinese_digits}", s):
        return True

    return False


def _block_merge(block_list: list[dict]) -> list[Chunk]:
    if len(block_list) == 0:
        return []
    elif len(block_list) == 1:
        return [
            Chunk(
                type=ChunkType.TEXT.value,
                text=block_list[0]["text"],
                image=Image(),
            )
        ]

    result_list = []
    current_text = block_list[0]["text"]
    before_left, _, before_right, _ = block_list[0]["bbox"]

    for i in range(1, len(block_list)):
        left, _, right, _ = block_list[i]["bbox"]
        if _alignment(
            block_list[i]["text"], current_text, left, right, before_left, before_right
        ):
            current_text += block_list[i]["text"]
            before_left, _, before_right, _ = block_list[i]["bbox"]
        else:
            result_list.append(
                Chunk(
                    type=ChunkType.TEXT.value,
                    text=current_text,
                    image=Image(),
                )
            )
            current_text = block_list[i]["text"]
            before_left, _, before_right, _ = block_list[i]["bbox"]

    result_list.append(
        Chunk(
            type=ChunkType.TEXT.value,
            text=current_text,
            image=Image(),
        )
    )
    return result_list


def _alignment(text1, text2, left, right, before_left, before_right) -> bool:
    RIGHT_BRAGE = 10
    BRAGE = 1
    LEFT_BRAGE = 10
    punc = _ends_with_chinese_punctuation(text1) or _ends_with_chinese_punctuation(
        text2
    )
    right_alignment = abs(right - before_right) < BRAGE or (
        punc and abs(right - before_right) < RIGHT_BRAGE
    )
    left_alignment = abs(left - before_left) < BRAGE

    if left - before_left > LEFT_BRAGE:
        return False
    elif right_alignment:
        return True
    elif right < before_right and (left_alignment or left < before_left):
        return True
    else:
        return False


def _ends_with_chinese_punctuation(s: str) -> bool:
    punctuation = {
        "。",
        "，",
        "！",
        "？",
        "；",
        "：",
        """, """,
        "'",
        "'",
        "（",
        "）",
        "【",
        "】",
        "《",
        "》",
        "、",
        "…",
        "—",
        "～",
        "!",
        ",",
        "?",
        ":",
        ";",
        '"',
        ".",
    }
    if not s:
        return False
    return s[-1] in punctuation
