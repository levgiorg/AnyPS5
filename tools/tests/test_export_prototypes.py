import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import export_prototypes

TOOL = Path(__file__).resolve().parents[1] / "export_prototypes.py"

ANYPS5_EXPORT = """
#include "SceTypes.hpp"
extern "C" {
int APS5_VABI sceAlphaOne(int value) {
    NotImplemented_nid_no_patch(__func__);
    return 0;
}
int APS5_VABI sceAlphaTwo(const char* text, void* out, std::size_t length) {
    NotImplemented_nid_no_patch(__func__);
    return 0;
}
int APS5_VABI sceAlphaThree(void) {
    NotImplemented_nid_no_patch(__func__);
    return 0;
}
}
"""

ANYPS5_TYPES = """
using AlphaEntry = void* (*)(void*);
"""

ANYPS5_LIBRARY_TYPES = """
#include "SceTypes.hpp"
int APS5_VABI sceAlphaFour(AlphaEntry entry, void* arg) {
    NotImplemented_nid_no_patch(__func__);
    return 0;
}
"""

PS5_SOURCE = """
int sceAlphaTwo(const char* text, void* out, size_t length);
int sceAlphaThree(int first, int second);
int sceAlphaFour(void* (*entry)(void*), void* arg);
int sceAlphaFive(int only);
int sceAlphaSix(void);
"""


class ExportPrototypesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.write("core/libs/prx/libSceAlpha/Export.cpp", ANYPS5_EXPORT)
        self.write("core/libs/prx/libSceAlpha/Types.hpp", ANYPS5_LIBRARY_TYPES)
        self.write("core/libs/SceTypes.hpp", ANYPS5_TYPES)
        self.write("homebrew/main.c", PS5_SOURCE)

    def tearDown(self):
        self.directory.cleanup()

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def exports(self):
        return export_prototypes.anyps5_exports(self.root)

    def typedefs(self):
        return export_prototypes.function_pointer_typedefs(self.root / "core" / "libs")

    def test_export_prototypes_are_read(self):
        exports = self.exports()
        self.assertIn("sceAlphaOne", exports)
        self.assertEqual(exports["sceAlphaOne"][0].library, "libSceAlpha")
        self.assertEqual(exports["sceAlphaOne"][0].parameters.arity, 1)
        self.assertEqual(exports["sceAlphaTwo"][0].parameters.arity, 3)
        self.assertEqual(exports["sceAlphaThree"][0].parameters.arity, 0)

    def test_a_declaration_and_a_call_are_told_apart(self):
        found = export_prototypes.observations("homebrew", self.root / "homebrew")
        kinds = {observation.name: observation.kind for observation in found}
        self.assertEqual(kinds["sceAlphaTwo"], "declaration")
        self.assertEqual(kinds["sceAlphaSix"], "declaration")

    def test_a_call_that_follows_a_keyword_is_a_call(self):
        self.write("homebrew/call.c", "int main() { return sceAlphaThree(1, 2); }\n")
        found = export_prototypes.observations("homebrew", self.root / "homebrew")
        calls = [observation for observation in found if observation.name == "sceAlphaThree"]
        self.assertTrue(any(observation.kind == "call" and observation.parameters.arity == 2
                            for observation in calls))

    def test_a_comma_inside_a_string_is_not_an_argument_separator(self):
        self.write("homebrew/text.c", 'sceAlphaFive("a, b, c");\n')
        found = export_prototypes.observations("homebrew", self.root / "homebrew")
        calls = [observation for observation in found if observation.name == "sceAlphaFive"]
        self.assertTrue(any(observation.parameters.arity == 1 for observation in calls))

    def test_a_function_pointer_alias_counts_as_a_pointer(self):
        typedefs = export_prototypes.function_pointer_typedefs(self.root / "core" / "libs")
        self.assertIn("AlphaEntry", typedefs)
        exports = self.exports()
        parameters = exports["sceAlphaFour"][0].parameters
        self.assertEqual(parameters.pointers(typedefs), [True, True])

    def test_a_mismatch_is_reported_with_its_evidence(self):
        exports = self.exports()
        found = export_prototypes.observations("homebrew", self.root / "homebrew")
        mismatches = export_prototypes.compare(exports, found, None, self.typedefs())
        names = {mismatch.export.name for mismatch in mismatches}
        self.assertIn("sceAlphaThree", names)
        self.assertNotIn("sceAlphaTwo", names)
        self.assertNotIn("sceAlphaFour", names)
        for mismatch in mismatches:
            self.assertTrue(mismatch.observation.evidence().startswith("homebrew:"))

    def test_the_report_and_the_json_list_the_mismatch(self):
        exports = self.exports()
        found = export_prototypes.observations("homebrew", self.root / "homebrew")
        mismatches = export_prototypes.compare(exports, found)
        text = export_prototypes.report(mismatches, [export_prototypes.Source("homebrew", "abc123")])
        self.assertIn("sceAlphaThree", text)
        self.assertIn("abc123", text)
        self.assertIn("libSceAlpha", text)

    def test_the_tool_runs_and_writes_its_json(self):
        output = self.root / "audit.json"
        result = subprocess.run(
            [sys.executable, str(TOOL), "--source", str(self.root),
             "--ps5", str(self.root / "homebrew"), "--json", str(output)],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(len(report["mismatches"]), 1)
        self.assertEqual(report["mismatches"][0]["export"], "sceAlphaThree")
        self.assertEqual(report["mismatches"][0]["library"], "libSceAlpha")
        self.assertEqual(report["mismatches"][0]["ps5"], "int, int")


if __name__ == "__main__":
    unittest.main()
