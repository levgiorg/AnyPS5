import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import import_audit
import nid_names

LIBRARIES = {
    "libSceSysCore": [
        "sceApplicationExitSpawn3",
        "sceApplicationKickCoredump3",
        "sceApplicationNotifyUnmountForExitSpawn",
        "sceApplicationSendResultOfDebuggerRestoreRequest",
        "sceApplicationSendResultOfDebuggerSaveRequest",
        "sceApplicationSwitchToPprNativeMode",
    ],
}
PENDING = re.compile(
    r"^int APS5_VABI (?P<name>\w+)\(void\) \{\n"
    r"    NotImplemented_nid_no_patch\(__func__\);\n"
    r"    return 0;\n"
    r"\}$", re.MULTILINE)


class PendingExportNidTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(os.environ.get("ANYPS5_SOURCE_ROOT", Path.cwd())).resolve()
        self.patched = self.root / "build" / "core" / "libs" / "libs"

    def source(self, library):
        return (self.root / "core" / "libs" / "prx" / library / "Export.cpp").read_text(encoding="utf-8")

    def exports(self, library):
        path = self.patched / f"{library}.prx"
        if not path.exists():
            self.skipTest(f"{path} is not built")
        return import_audit.read_exports(path)

    def test_every_pending_export_is_declared_as_a_throwing_function(self):
        for library, names in LIBRARIES.items():
            declared = {match.group("name") for match in PENDING.finditer(self.source(library))}
            for name in names:
                with self.subTest(library=library, export=name):
                    self.assertIn(name, declared)

    def test_every_pending_export_resolves_by_its_nid(self):
        for library, names in LIBRARIES.items():
            exports = self.exports(library)
            for name in names:
                with self.subTest(library=library, export=name):
                    self.assertIn(nid_names.compute_nid(name), exports)

    def test_a_pending_export_does_not_keep_its_plain_name(self):
        for library, names in LIBRARIES.items():
            exports = self.exports(library)
            for name in names:
                with self.subTest(library=library, export=name):
                    self.assertNotIn(name, exports)


if __name__ == "__main__":
    unittest.main()
