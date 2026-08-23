import tempfile
import unittest
import zipfile
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from tuxindrive.file_preview import MAX_TEXT_BYTES, PreviewError, preview_path


class FilePreviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _archive(self, name: str, entries: dict[str, str | bytes]) -> Path:
        path = self.root / name
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for member, value in entries.items():
                archive.writestr(member, value)
        return path

    def test_text_preview_is_local_bounded_and_utf8(self):
        path = self.root / "notes.md"
        path.write_text("Žluťoučký project note", encoding="utf-8")
        result = preview_path(path)
        self.assertEqual(result.kind, "text")
        self.assertIn("Žluťoučký", result.text)
        self.assertFalse(result.truncated)

    def test_binary_and_oversized_text_are_rejected(self):
        binary = self.root / "binary.txt"
        binary.write_bytes(b"hello\0world")
        with self.assertRaisesRegex(PreviewError, "binary"):
            preview_path(binary)
        oversized = self.root / "large.log"
        oversized.write_bytes(b"a" * (MAX_TEXT_BYTES + 1))
        with self.assertRaisesRegex(PreviewError, "preview limit"):
            preview_path(oversized)

    def test_symlink_is_never_followed(self):
        target = self.root / "secret.txt"
        target.write_text("secret", encoding="utf-8")
        link = self.root / "link.txt"
        link.symlink_to(target)
        with self.assertRaisesRegex(PreviewError, "Symbolic links"):
            preview_path(link)

    def test_directory_preview_does_not_enumerate_children(self):
        folder = self.root / "folder"
        folder.mkdir()
        (folder / "private-name.txt").write_text("private", encoding="utf-8")
        result = preview_path(folder)
        self.assertEqual(result.format_label, "Folder")
        self.assertNotIn("private-name", result.text)

    def test_image_bytes_are_bounded_for_the_gtk_decoder(self):
        image = self.root / "photo.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\npreview-bytes")
        result = preview_path(image)
        self.assertEqual(result.kind, "image")
        self.assertEqual(result.image_bytes, image.read_bytes())

    def test_docx_text_is_extracted_from_bounded_xml(self):
        path = self._archive(
            "document.docx",
            {"word/document.xml": '<w:document xmlns:w="urn:w"><w:p><w:r><w:t>Hello Word</w:t></w:r></w:p></w:document>'},
        )
        result = preview_path(path)
        self.assertEqual(result.format_label, "Word document")
        self.assertIn("Hello Word", result.text)

    def test_xlsx_shared_strings_and_cells_are_previewed(self):
        path = self._archive(
            "sheet.xlsx",
            {
                "xl/sharedStrings.xml": '<sst xmlns="urn:x"><si><t>Budget</t></si></sst>',
                "xl/worksheets/sheet1.xml": '<worksheet xmlns="urn:x"><c r="A1" t="s"><v>0</v></c><c r="B1"><v>42</v></c></worksheet>',
            },
        )
        result = preview_path(path)
        self.assertIn("A1: Budget", result.text)
        self.assertIn("B1: 42", result.text)

    def test_pptx_and_odt_text_are_previewed(self):
        presentation = self._archive(
            "slides.pptx",
            {"ppt/slides/slide1.xml": '<p:sld xmlns:p="urn:p" xmlns:a="urn:a"><a:t>Roadmap</a:t></p:sld>'},
        )
        self.assertIn("Roadmap", preview_path(presentation).text)
        document = self._archive(
            "document.odt",
            {"content.xml": '<office:document xmlns:office="urn:o" xmlns:text="urn:t"><text:p>Hello ODT</text:p></office:document>'},
        )
        self.assertIn("Hello ODT", preview_path(document).text)

    def test_unsafe_office_archive_is_rejected(self):
        path = self._archive(
            "unsafe.docx",
            {"../escape.xml": "bad", "word/document.xml": '<w:document xmlns:w="urn:w" />'},
        )
        with self.assertRaisesRegex(PreviewError, "unsafe"):
            preview_path(path)

    def test_high_compression_ratio_document_is_rejected(self):
        path = self.root / "bomb.docx"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("word/document.xml", b"A" * 1_000_000)
        with self.assertRaisesRegex(PreviewError, "compression-ratio"):
            preview_path(path)

    @patch("tuxindrive.file_preview.shutil.which", return_value=None)
    def test_pdf_has_clear_optional_extractor_fallback(self, _which):
        path = self.root / "document.pdf"
        path.write_bytes(b"%PDF-1.7\nminimal")
        result = preview_path(path)
        self.assertEqual(result.format_label, "PDF document")
        self.assertIn("pdftotext", result.text)

    @patch("tuxindrive.file_preview.shutil.which", return_value="/usr/bin/pdftotext")
    def test_pdf_extraction_is_page_limited_private_and_shell_free(self, _which):
        path = self.root / "document.pdf"
        path.write_bytes(b"%PDF-1.7\nminimal")
        invocation = {}

        def extract(command, **kwargs):
            invocation["command"] = command
            invocation["kwargs"] = kwargs
            Path(command[-1]).write_text("First pages", encoding="utf-8")
            return CompletedProcess(command, 0)

        with patch("tuxindrive.file_preview.subprocess.run", side_effect=extract):
            result = preview_path(path)
        self.assertEqual(result.text, "First pages")
        self.assertEqual(
            invocation["command"][:6],
            ["/usr/bin/pdftotext", "-f", "1", "-l", "3", "-layout"],
        )
        self.assertNotEqual(Path(invocation["command"][-2]), path)
        self.assertEqual(invocation["kwargs"]["timeout"], 8)
        self.assertNotIn("shell", invocation["kwargs"])

    def test_unknown_format_is_not_opened(self):
        path = self.root / "program.exe"
        path.write_bytes(b"MZ")
        result = preview_path(path)
        self.assertEqual(result.format_label, "Preview unavailable")
        self.assertIn("system application", result.text)


if __name__ == "__main__":
    unittest.main()
