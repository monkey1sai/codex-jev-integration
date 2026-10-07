import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from inventory import build_inventory, InventoryFailure, MAX_SKILL_BYTES


NOW = "2026-10-07T12:00:00Z"


def snapshot(**updates):
    data = {"captured_at": NOW, "tools": ["private_tool_name"], "provenance": "caller_runtime"}
    data.update(updates)
    return data


def spec(resource_id="read", **updates):
    data = {"id": resource_id, "kind": "tool", "description": "Read bounded evidence",
            "binding": "private_tool_name", "in_scope": True,
            "when_to_use": "When local source evidence is necessary", "limits": ["Read only"],
            "requires": [], "conflicts": []}
    data.update(updates)
    return data


class InventoryTests(unittest.TestCase):
    def build(self, specs, **kwargs):
        return build_inventory(snapshot(), specs, now=NOW, **kwargs)

    def test_stale_future_and_boundaries(self):
        for captured, code in [("2026-10-07T11:54:59Z", "STALE_RUNTIME_SNAPSHOT"),
                               ("2026-10-07T12:00:06Z", "FUTURE_RUNTIME_SNAPSHOT")]:
            with self.assertRaisesRegex(InventoryFailure, code):
                build_inventory(snapshot(captured_at=captured), [], now=NOW)
        for captured in ["2026-10-07T11:55:00Z", "2026-10-07T12:00:05Z"]:
            self.assertFalse(build_inventory(snapshot(captured_at=captured), [], now=NOW)["fallback"])

    def test_tools_derive_availability_not_spec_flag(self):
        result = self.build([spec(available=False), spec("missing", binding="absent", available=True)])
        self.assertEqual([x["id"] for x in result["candidates"]], ["read"])
        self.assertTrue(result["candidates"][0]["available"])
        self.assertEqual(result["provenance"]["excluded"], [{"id": "missing", "reason": "TOOL_NOT_IN_SNAPSHOT"}])

    def test_required_unavailable_and_outscope_are_retained(self):
        result = self.build([spec("missing", binding="absent"), spec("scope", in_scope=False)],
                            required_ids=["missing", "scope"])
        self.assertTrue(result["fallback"])
        self.assertEqual(len(result["candidates"]), 2)
        self.assertEqual(result["provenance"]["required_unavailable"], ["missing", "scope"])

    def test_skill_hash_existence_and_no_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp).resolve() / "SKILL.md"
            content = b"# Explicit skill\nDo bounded work.\n"
            path.write_bytes(content)
            result = self.build([spec(kind="skill", binding=str(path))])
            self.assertEqual(result["provenance"]["skill_sha256"]["read"], hashlib.sha256(content).hexdigest())
            self.assertEqual(path.read_bytes(), content)
            path.unlink()
            self.assertEqual(self.build([spec(kind="skill", binding=str(path))])["candidates"], [])

    def test_invalid_and_oversized_skill_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp).resolve() / "SKILL.md"
            path.write_bytes(b"x" * (MAX_SKILL_BYTES + 1))
            for binding in [str(path), "relative/SKILL.md", str(path.parent)]:
                self.assertEqual(self.build([spec(kind="skill", binding=binding)])["candidates"], [])

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = root / "target"
            target.write_text("skill")
            link = root / "SKILL.md"
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("Host does not permit creating a test symlink")
            result = self.build([spec(kind="skill", binding=str(link))])
            self.assertEqual(result["provenance"]["excluded"][0]["reason"], "UNSAFE_SKILL_BINDING")

    def test_dedup_requires_explicit_key_and_required_wins(self):
        rows = [spec("first", capability_key="read"), spec("second", capability_key="read"), spec("other")]
        result = self.build(rows, required_ids=["second"])
        self.assertEqual([x["id"] for x in result["candidates"]], ["second", "other"])
        result = self.build(rows, required_ids=["first", "second"])
        self.assertEqual(len(result["candidates"]), 3)

    def test_duplicate_ids_and_required_rejected(self):
        with self.assertRaisesRegex(InventoryFailure, "DUPLICATE_RESOURCE_ID"):
            self.build([spec(), spec()])
        with self.assertRaisesRegex(InventoryFailure, "DUPLICATE_RESOURCE_IDS"):
            self.build([spec()], required_ids=["read", "read"])
        with self.assertRaisesRegex(InventoryFailure, "UNKNOWN_REQUIRED_RESOURCE"):
            self.build([spec()], required_ids=["unknown"])

    def test_excluded_dependency_visible_fallback(self):
        result = self.build([spec(requires=["dep"]), spec("dep", binding="absent")])
        self.assertTrue(result["fallback"])
        self.assertIn("RESOURCE_DEPENDENCY_UNAVAILABLE", result["reasons"])
        self.assertEqual(result["candidates"][0]["requires"], ["dep"])

    def test_excluded_conflict_visible_fallback(self):
        result = self.build([spec(conflicts=["dep"]), spec("dep", binding="absent")])
        self.assertTrue(result["fallback"])
        self.assertIn("RESOURCE_CONFLICT_REFERENCE_EXCLUDED", result["reasons"])

    def test_metadata_privacy_and_input_not_mutated(self):
        rows, snap = [spec()], snapshot()
        original = json.dumps([rows, snap], sort_keys=True)
        result = build_inventory(snap, rows, now=NOW)
        provider = json.dumps(result["candidates"])
        self.assertNotIn("private_tool_name", provider)
        self.assertNotIn("binding", provider)
        self.assertEqual(set(result["candidates"][0]), {"id", "kind", "description", "available", "in_scope",
            "when_to_use", "limits", "requires", "conflicts"})
        self.assertEqual(json.dumps([rows, snap], sort_keys=True), original)
        self.assertEqual(result["provenance"]["availability"], "caller_reported")
        self.assertFalse(result["provenance"]["api_can_read_runtime"])

    def test_limits_and_reference_validation(self):
        for bad in [spec(description="x" * 241), spec(limits=["x"] * 9), spec(requires=["missing"])]:
            with self.assertRaises(InventoryFailure):
                self.build([bad])
        with self.assertRaises(InventoryFailure):
            self.build([spec(str(x)) for x in range(25)])


if __name__ == "__main__":
    unittest.main()
