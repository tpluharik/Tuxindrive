"""Bounded, opt-in local previews for search results.

Previewing is deliberately separate from indexing: this module reads only the
single file selected by the user after the search-window feature flag is
enabled.  It never follows symbolic links or invokes a shell.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from defusedxml import ElementTree as ET


MAX_TEXT_BYTES = 1024 * 1024
MAX_PREVIEW_CHARACTERS = 60_000
MAX_BINARY_BYTES = 32 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 2_048
MAX_ARCHIVE_ENTRY_BYTES = 8 * 1024 * 1024
MAX_ARCHIVE_EXPANDED_BYTES = 64 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100
MAX_PDF_PAGES = 3

TEXT_SUFFIXES = {
    ".txt", ".md", ".rst", ".log", ".csv", ".tsv", ".json", ".jsonl",
    ".yaml", ".yml", ".toml", ".xml", ".html", ".htm", ".css", ".js",
    ".ts", ".py", ".sh", ".ini", ".cfg", ".conf", ".sql",
}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
OFFICE_SUFFIXES = {".odt", ".ods", ".docx", ".xlsx", ".pptx"}


class PreviewError(RuntimeError):
    """The selected item cannot be previewed safely."""


@dataclass(frozen=True, slots=True)
class PreviewData:
    kind: str
    format_label: str
    text: str = ""
    image_bytes: bytes = b""
    truncated: bool = False


def _read_regular(path: Path, limit: int) -> bytes:
    try:
        before = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise PreviewError("The selected file is no longer available locally") from exc
    if not stat.S_ISREG(before.st_mode):
        raise PreviewError("Only regular local files can be previewed")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise PreviewError("The selected file could not be opened without following links") from exc
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode):
            raise PreviewError("Only regular local files can be previewed")
        if (before.st_dev, before.st_ino) != (details.st_dev, details.st_ino):
            raise PreviewError("The selected file changed before its preview could be opened")
        if details.st_size > limit:
            raise PreviewError(f"The selected file exceeds the {limit // (1024 * 1024)} MiB preview limit")
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(descriptor, min(128 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        if len(content) > limit:
            raise PreviewError("The selected file changed while its bounded preview was being read")
        return content
    finally:
        os.close(descriptor)


def _bounded_text(value: str) -> tuple[str, bool]:
    cleaned = value.replace("\x00", "").strip()
    if len(cleaned) <= MAX_PREVIEW_CHARACTERS:
        return cleaned, False
    return cleaned[:MAX_PREVIEW_CHARACTERS].rstrip() + "\n\n[Preview truncated]", True


def _decode_text(content: bytes) -> tuple[str, bool]:
    if b"\x00" in content[:4096] and not content.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise PreviewError("The selected file appears to contain binary data")
    encodings = ("utf-8-sig", "utf-16") if content.startswith((b"\xff\xfe", b"\xfe\xff")) else ("utf-8-sig",)
    for encoding in encodings:
        try:
            return _bounded_text(content.decode(encoding))
        except UnicodeDecodeError:
            continue
    raise PreviewError("Text preview supports UTF-8 and BOM-marked UTF-16 files")


def _validated_archive(content: bytes) -> tuple[zipfile.ZipFile, dict[str, zipfile.ZipInfo]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
        infos = archive.infolist()
    except (OSError, zipfile.BadZipFile) as exc:
        raise PreviewError("The document container is malformed") from exc
    if len(infos) > MAX_ARCHIVE_ENTRIES:
        archive.close()
        raise PreviewError("The document contains too many archive entries")
    entries: dict[str, zipfile.ZipInfo] = {}
    expanded = 0
    for info in infos:
        member = Path(info.filename)
        if (
            info.filename in entries
            or member.is_absolute()
            or ".." in member.parts
            or "\\" in info.filename
        ):
            archive.close()
            raise PreviewError("The document contains an unsafe or duplicate archive entry")
        if info.file_size > MAX_ARCHIVE_ENTRY_BYTES:
            archive.close()
            raise PreviewError("A document entry exceeds the preview limit")
        expanded += info.file_size
        if expanded > MAX_ARCHIVE_EXPANDED_BYTES:
            archive.close()
            raise PreviewError("The expanded document exceeds the preview limit")
        if info.file_size and not info.compress_size:
            archive.close()
            raise PreviewError("The document has an invalid compression ratio")
        if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
            archive.close()
            raise PreviewError("The document exceeds the preview compression-ratio limit")
        entries[info.filename] = info
    return archive, entries


def _xml(archive: zipfile.ZipFile, entries: dict[str, zipfile.ZipInfo], name: str):
    info = entries.get(name)
    if info is None:
        raise PreviewError(f"The document has no {name}")
    try:
        return ET.fromstring(archive.read(info))
    except Exception as exc:
        raise PreviewError("The document XML is unsafe or malformed") from exc


def _local_name(element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _paragraph_text(root, *, text_tag: str = "t") -> list[str]:
    paragraphs: list[str] = []
    for node in root.iter():
        if _local_name(node) not in {"p", "h"}:
            continue
        value = "".join((part.text or "") for part in node.iter() if _local_name(part) == text_tag).strip()
        if value:
            paragraphs.append(value)
    if not paragraphs:
        value = " ".join((node.text or "").strip() for node in root.iter() if _local_name(node) == text_tag and (node.text or "").strip())
        if value:
            paragraphs.append(value)
    return paragraphs


def _office_preview(content: bytes, suffix: str) -> PreviewData:
    archive, entries = _validated_archive(content)
    try:
        if suffix in {".odt", ".ods"}:
            root = _xml(archive, entries, "content.xml")
            values = []
            for node in root.iter():
                if _local_name(node) in {"p", "h"}:
                    value = "".join(node.itertext()).strip()
                    if value:
                        values.append(value)
            label = "OpenDocument text" if suffix == ".odt" else "OpenDocument spreadsheet"
        elif suffix == ".docx":
            root = _xml(archive, entries, "word/document.xml")
            values = _paragraph_text(root)
            label = "Word document"
        elif suffix == ".xlsx":
            shared: list[str] = []
            if "xl/sharedStrings.xml" in entries:
                strings = _xml(archive, entries, "xl/sharedStrings.xml")
                for item in strings.iter():
                    if _local_name(item) == "si":
                        shared.append("".join((node.text or "") for node in item.iter() if _local_name(node) == "t"))
            values = []
            for name in sorted(entry for entry in entries if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", entry)):
                root = _xml(archive, entries, name)
                values.append(f"[{Path(name).stem}]")
                for cell in (node for node in root.iter() if _local_name(node) == "c"):
                    raw = next(((node.text or "") for node in cell.iter() if _local_name(node) == "v"), "")
                    inline = "".join((node.text or "") for node in cell.iter() if _local_name(node) == "t")
                    value = inline or raw
                    if cell.attrib.get("t") == "s" and raw.isdigit() and int(raw) < len(shared):
                        value = shared[int(raw)]
                    if value:
                        reference = cell.attrib.get("r", "cell")
                        values.append(f"{reference}: {value}")
            label = "Excel spreadsheet"
        else:
            values = []
            slides = sorted(
                (name for name in entries if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
                key=lambda name: int(re.search(r"(\d+)", Path(name).stem).group(1)),
            )
            for number, name in enumerate(slides, 1):
                root = _xml(archive, entries, name)
                text = " ".join((node.text or "").strip() for node in root.iter() if _local_name(node) == "t" and (node.text or "").strip())
                if text:
                    values.append(f"Slide {number}\n{text}")
            label = "PowerPoint presentation"
    finally:
        archive.close()
    text, truncated = _bounded_text("\n".join(values) or "No previewable text was found in this document.")
    return PreviewData("text", label, text=text, truncated=truncated)


def _pdf_preview(content: bytes) -> PreviewData:
    if not content.startswith(b"%PDF-"):
        raise PreviewError("The selected file does not have a valid PDF header")
    executable = shutil.which("pdftotext")
    if executable is None:
        return PreviewData(
            "text",
            "PDF document",
            text="PDF text preview requires the optional pdftotext utility. The file was not opened or sent anywhere.",
        )
    with tempfile.TemporaryDirectory(prefix="tuxindrive-preview-") as directory:
        root = Path(directory)
        os.chmod(root, 0o700)
        source = root / "document.pdf"
        output = root / "preview.txt"
        source.write_bytes(content)
        os.chmod(source, 0o600)
        try:
            completed = subprocess.run(
                [executable, "-f", "1", "-l", str(MAX_PDF_PAGES), "-layout", str(source), str(output)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=8,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PreviewError("PDF text extraction did not complete safely") from exc
        if completed.returncode != 0 or not output.is_file():
            raise PreviewError("No previewable PDF text was produced")
        text, truncated = _decode_text(_read_regular(output, MAX_TEXT_BYTES))
        return PreviewData("text", f"PDF document (first {MAX_PDF_PAGES} pages)", text=text or "No text was found.", truncated=truncated)


def preview_path(path: Path | str) -> PreviewData:
    """Return a bounded preview for one user-selected local search result."""

    selected = Path(path)
    if selected.is_symlink():
        raise PreviewError("Symbolic links are not previewed")
    if selected.is_dir():
        return PreviewData("text", "Folder", text="Folder preview does not enumerate its contents.")
    suffix = selected.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        text, truncated = _decode_text(_read_regular(selected, MAX_TEXT_BYTES))
        return PreviewData("text", "Text file", text=text or "This text file is empty.", truncated=truncated)
    if suffix in IMAGE_SUFFIXES:
        content = _read_regular(selected, MAX_BINARY_BYTES)
        return PreviewData("image", "Image", image_bytes=content)
    if suffix in OFFICE_SUFFIXES:
        return _office_preview(_read_regular(selected, MAX_BINARY_BYTES), suffix)
    if suffix == ".pdf":
        return _pdf_preview(_read_regular(selected, MAX_BINARY_BYTES))
    return PreviewData(
        "text",
        "Preview unavailable",
        text="This file type is not previewed. Use Open selected to open it with the system application.",
    )
