from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

from valisync.gui.views.recent_files import RecentFiles


def _settings(tmp_path: Path) -> QSettings:
    # INI 形式でテスト分離 (レジストリ/既定を汚さない)
    return QSettings(str(tmp_path / "recent.ini"), QSettings.Format.IniFormat)


def test_add_prepends_dedups_and_caps(tmp_path: Path) -> None:
    rf = RecentFiles(max_items=3, settings=_settings(tmp_path))
    for p in ["a.mf4", "b.mf4", "c.mf4", "a.mf4", "d.mf4"]:
        rf.add(p)
    # a は再追加で先頭へ、上限3で b が押し出される
    assert rf.items() == ["d.mf4", "a.mf4", "c.mf4"]


def test_persists_across_instances(tmp_path: Path) -> None:
    path = str(tmp_path / "recent.ini")
    s1 = QSettings(path, QSettings.Format.IniFormat)
    RecentFiles(settings=s1).add("x.mf4")
    s1.sync()  # flush to disk
    s2 = QSettings(path, QSettings.Format.IniFormat)  # independent instance
    assert RecentFiles(settings=s2).items() == ["x.mf4"]


def test_existing_filters_missing(tmp_path: Path) -> None:
    real = tmp_path / "real.csv"
    real.write_text("t,v\n0,1\n", encoding="utf-8")
    rf = RecentFiles(settings=_settings(tmp_path))
    rf.add(str(real))
    rf.add(str(tmp_path / "gone.csv"))
    assert rf.existing() == [str(real)]


def test_clear_removes_all(tmp_path: Path) -> None:
    rf = RecentFiles(settings=_settings(tmp_path))
    rf.add("a.mf4")
    rf.clear()
    assert rf.items() == []
