from tests import signal_safety as _signal_safety  # noqa: F401

import tempfile
import unittest
import zipfile
from pathlib import Path

from tuxindrive.collaboration import CollaborationError, CollaborationWorkspace, ODFAdapter, TextCRDT, TextOperation, document_capability


class CollaborationTests(unittest.TestCase):
    def test_offline_peers_converge_independent_of_merge_order(self):
        seed = TextCRDT("seed")
        initial = seed.insert(0, "hi")
        alice = TextCRDT("alice", initial)
        bob = TextCRDT("bob", initial)
        alice_ops = alice.insert(2, " A")
        bob_ops = bob.insert(2, " B")
        first = TextCRDT("one", [*initial, *alice_ops, *bob_ops])
        second = TextCRDT("two", [*bob_ops, *initial, *alice_ops])
        self.assertEqual(first.text, second.text)
        self.assertIn(" A", first.text)
        self.assertIn(" B", first.text)

    def test_workspace_keeps_state_separate_and_exports_checkpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "notes.md"
            source.write_text("Hello", encoding="utf-8")
            workspace = CollaborationWorkspace(folder, source.name, "device one")
            crdt = workspace.import_checkpoint(source)
            workspace.persist(crdt.insert(5, " world"))
            merged = workspace.load()
            workspace.export_checkpoint(source, merged)
            self.assertEqual(source.read_text(encoding="utf-8"), "Hello world")
            self.assertTrue((Path(folder) / ".tuxdrive-collaboration").is_dir())

    def test_conflicting_immutable_operation_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = CollaborationWorkspace(folder, "notes", "device")
            crdt = TextCRDT("device")
            operation = crdt.insert(0, "x")[0]
            workspace.persist([operation])
            path = next((workspace.root / "operations").glob("*/*.json"))
            path.write_text(path.read_text().replace('"x"', '"y"'), encoding="utf-8")
            with self.assertRaises(CollaborationError):
                workspace.persist([operation])

    def test_review_and_encrypted_ephemeral_presence(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = CollaborationWorkspace(folder, "notes", "alice")
            workspace.add_review("comment", "Please verify", 1, 3)
            workspace.add_review("approval", "Approved")
            self.assertEqual({item.kind for item in workspace.reviews()}, {"approval", "comment"})
            key = b"k" * 32
            workspace.write_presence(key, 4, 7, ttl=5)
            self.assertEqual(workspace.read_presence(key)[0]["cursor"], 4)
            with self.assertRaises(CollaborationError):
                workspace.read_presence(b"z" * 32)
            self.assertFalse((workspace.root / "audit.json").exists())

    def test_odt_structured_round_trip_is_deterministic_and_recoverable(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "document.odt"
            content = b'''<?xml version="1.0"?><office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><office:text><text:p text:style-name="Body"><text:span>Original</text:span></text:p><office:annotation><text:p>Comment</text:p></office:annotation><text:tracked-changes/></office:text></office:body></office:document-content>'''
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("mimetype", "application/vnd.oasis.opendocument.text")
                archive.writestr("content.xml", content)
            document = ODFAdapter.load(source)
            self.assertEqual(document.paragraphs[0].text, "Original")
            self.assertTrue(document.tracked_changes)
            document.paragraphs[0].text = "Changed"
            first = Path(folder) / "first.odt"
            second = Path(folder) / "second.odt"
            ODFAdapter.export(document, first)
            ODFAdapter.export(document, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with zipfile.ZipFile(first) as archive:
                self.assertEqual(archive.read("TuxInDrive/original-content.xml"), content)
            self.assertEqual(ODFAdapter.load(first).paragraphs[0].text, "Changed")

    def test_ods_cells_and_formula_are_structured(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "sheet.ods"
            content = b'''<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><office:spreadsheet><table:table table:name="Data"><table:table-row><table:table-cell table:formula="of:=1+1"><text:p>2</text:p></table:table-cell></table:table-row></table:table></office:spreadsheet></office:body></office:document-content>'''
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet")
                archive.writestr("content.xml", content)
            document = ODFAdapter.load(source)
            self.assertEqual(document.cells[0].formula, "of:=1+1")
            document.cells[0].formula = "of:=2+2"
            document.cells[0].value = "4"
            output = Path(folder) / "out.ods"
            ODFAdapter.export(document, output)
            updated = ODFAdapter.load(output)
            self.assertEqual((updated.cells[0].formula, updated.cells[0].value), ("of:=2+2", "4"))

    def test_unsafe_binary_formats_never_claim_realtime_support(self):
        for name in ("report.docx", "book.xlsx", "review.pdf"):
            self.assertEqual(document_capability(name)["mode"], "lock-version-review")

    def test_odf_zip_bomb_ratio_is_rejected_before_expansion(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "bomb.odt"
            with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("mimetype", "application/vnd.oasis.opendocument.text")
                archive.writestr("content.xml", b"A" * (2 * 1024 * 1024))
            with self.assertRaisesRegex(CollaborationError, "compression-ratio"):
                ODFAdapter.load(source)

    def test_deep_crdt_chain_uses_bounded_iterative_traversal(self):
        crdt = TextCRDT("device")
        crdt.insert(0, "x" * 5000)
        self.assertEqual(len(crdt.text), 5000)

    def test_unreachable_crdt_cycle_is_rejected(self):
        operations = [
            TextOperation("a:00000000000000000001", "a", 1, "insert", after="b:00000000000000000001", value="a"),
            TextOperation("b:00000000000000000001", "b", 1, "insert", after="a:00000000000000000001", value="b"),
        ]
        with self.assertRaisesRegex(CollaborationError, "cycle"):
            _ = TextCRDT("reader", operations).text

    def test_unsafe_xml_entities_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "entities.odt"
            content = b'<!DOCTYPE x [<!ENTITY boom "boom">]><x>&boom;</x>'
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("mimetype", "application/vnd.oasis.opendocument.text")
                archive.writestr("content.xml", content)
            with self.assertRaisesRegex(CollaborationError, "unsafe or malformed"):
                ODFAdapter.load(source)


if __name__ == "__main__":
    unittest.main()
