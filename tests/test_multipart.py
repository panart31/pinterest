"""T09–T14: юнит-тесты разбора multipart/form-data."""

from __future__ import annotations

import pytest

from server.http.multipart import (
    MultipartError,
    boundary_from_content_type,
    find_part,
    parse_multipart,
)

PNG = bytes.fromhex("89504e470d0a1a0a")


def build_multipart(parts: list[dict], boundary: str = "----MosaicBoundary",
                    quote: bool = False) -> tuple[bytes, str]:
    """Собирает тело multipart/form-data из описаний частей."""
    chunks: list[bytes] = []
    for part in parts:
        disposition = f'form-data; name="{part["name"]}"'
        if part.get("filename") is not None:
            disposition += f'; filename="{part["filename"]}"'
        header = f"--{boundary}\r\nContent-Disposition: {disposition}\r\n"
        if part.get("content_type"):
            header += f"Content-Type: {part['content_type']}\r\n"
        chunks.append(header.encode("utf-8") + b"\r\n" + part["data"] + b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    quoted = f'"{boundary}"' if quote else boundary
    return b"".join(chunks), f"multipart/form-data; boundary={quoted}"


# T09
def test_single_file_part():
    body, content_type = build_multipart([
        {"name": "image", "filename": "photo.png", "data": PNG,
         "content_type": "image/png"},
        {"name": "caption", "data": "Закат".encode("utf-8")},
    ])
    parts = parse_multipart(body, content_type)
    assert len(parts) == 2
    image = find_part(parts, "image")
    assert image is not None
    assert image.filename == "photo.png"
    assert image.data == PNG
    assert image.content_type == "image/png"


# T10
def test_boundary_can_be_quoted():
    body, content_type = build_multipart(
        [{"name": "caption", "data": b"text"}], quote=True)
    boundary = boundary_from_content_type(content_type)
    assert boundary == "----MosaicBoundary"
    assert parse_multipart(body, content_type)[0].data == b"text"


# T11
def test_filename_extracted():
    body, content_type = build_multipart([
        {"name": "image", "filename": "my photo.jpg", "data": b"\xff\xd8\xff"},
    ])
    part = parse_multipart(body, content_type)[0]
    assert part.filename == "my photo.jpg"


# T12
def test_cyrillic_caption_and_filename():
    body, content_type = build_multipart([
        {"name": "image", "filename": "кот.png", "data": PNG},
        {"name": "caption", "data": "Кот на подоконнике".encode("utf-8")},
    ])
    parts = parse_multipart(body, content_type)
    assert find_part(parts, "image").filename == "кот.png"
    assert find_part(parts, "caption").data.decode("utf-8") == "Кот на подоконнике"


# T13
def test_too_many_parts_rejected():
    parts = [{"name": f"f{i}", "data": b"x"} for i in range(5)]
    body, content_type = build_multipart(parts)
    with pytest.raises(MultipartError):
        parse_multipart(body, content_type, max_parts=3)


# T14
def test_missing_boundary_rejected():
    with pytest.raises(MultipartError):
        boundary_from_content_type("multipart/form-data")
    with pytest.raises(MultipartError):
        parse_multipart(b"data", "application/json")


def test_empty_form_rejected():
    with pytest.raises(MultipartError):
        parse_multipart(b"--b--\r\n", "multipart/form-data; boundary=b")


def test_binary_data_preserved():
    data = bytes(range(256))
    body, content_type = build_multipart([
        {"name": "image", "filename": "raw.bin", "data": data},
    ])
    assert parse_multipart(body, content_type)[0].data == data
