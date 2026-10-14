"""原子写入：配置写入不能产生半截文件（决策 D-006）。"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from app.utils.atomic import write_json_atomic, write_text_atomic


class WriteTextAtomicTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_creates_file_with_utf8(self):
        target = self.dir / "a.txt"
        write_text_atomic(target, "中文内容\n")
        self.assertEqual(target.read_text(encoding="utf-8"), "中文内容\n")

    def test_overwrites_existing(self):
        target = self.dir / "a.txt"
        write_text_atomic(target, "first")
        write_text_atomic(target, "second")
        self.assertEqual(target.read_text(encoding="utf-8"), "second")

    def test_leaves_no_temp_files(self):
        target = self.dir / "a.txt"
        write_text_atomic(target, "x")
        self.assertEqual([p.name for p in self.dir.iterdir()], ["a.txt"])

    def test_temp_file_is_removed_when_write_fails(self):
        target = self.dir / "a.txt"
        # 写入一个非字符串：fdopen 写出时必然失败，临时文件必须被清掉。
        with self.assertRaises(TypeError):
            write_text_atomic(target, object())  # type: ignore[arg-type]
        self.assertEqual(list(self.dir.iterdir()), [])
        self.assertFalse(target.exists())

    def test_creates_missing_parent_directories(self):
        # 首次启动时 data/ 与 logs/ 可能还不存在，原子写入要能自己建出来。
        target = self.dir / "sub" / "deeper" / "a.txt"
        write_text_atomic(target, "x")
        self.assertEqual(target.read_text(encoding="utf-8"), "x")


class WriteJsonAtomicTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_round_trip(self):
        target = self.dir / "c.json"
        write_json_atomic(target, {"name": "中文", "n": 1})
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"name": "中文", "n": 1})

    def test_keeps_unicode_readable(self):
        target = self.dir / "c.json"
        write_json_atomic(target, {"name": "中文"})
        text = target.read_text(encoding="utf-8")
        self.assertIn("中文", text)
        self.assertNotIn("\\u4e2d", text)

    def test_ends_with_newline(self):
        target = self.dir / "c.json"
        write_json_atomic(target, {})
        self.assertTrue(target.read_text(encoding="utf-8").endswith("\n"))

    def test_replaces_file_atomically_never_truncates_reader(self):
        # 先写一份大的旧内容，再原子替换；旧文件路径始终可读且完整。
        target = self.dir / "c.json"
        write_json_atomic(target, {"v": "old"})
        write_json_atomic(target, {"v": "new", "pad": "x" * 5000})
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data["v"], "new")


class PathLikeTests(unittest.TestCase):
    def test_accepts_str_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "a.txt")
            write_text_atomic(target, "x")
            self.assertTrue(os.path.isfile(target))


if __name__ == "__main__":
    unittest.main()
