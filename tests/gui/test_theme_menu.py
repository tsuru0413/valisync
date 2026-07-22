"""View>テーマ radio — 排他・現 mode checked・保存のみ (再起動反映・spec §11)。"""

from __future__ import annotations

from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.app import build_main_window
from valisync.gui.theme import apply as apply_mod
from valisync.gui.theme.apply import load_theme_mode, save_theme_mode
from valisync.gui.theme.tokens import DARK, ThemeMode, active, set_active


def _theme_actions(window):
    return {a.text(): a for a in window._theme_group.actions()}


def test_menu_reflects_saved_mode_without_saving(qtbot: QtBot, monkeypatch):
    """構築時 checked 同期が save_theme_mode を誘発しない (二重発火ガード)。

    注意: 事前保存は patch の**前**に本物で行う (patch 後の re-import は
    patched 版を掴むため)。
    """
    save_theme_mode(ThemeMode.LIGHT)  # 本物で事前保存
    calls: list[object] = []
    monkeypatch.setattr(apply_mod, "save_theme_mode", lambda m: calls.append(m))
    try:
        window = build_main_window()
        qtbot.addWidget(window)
        acts = _theme_actions(window)
        assert acts["ライト"].isChecked()
        assert not acts["ダーク"].isChecked()
        assert calls == []  # 構築では保存が一度も呼ばれない
    finally:
        set_active(DARK)
        apply_mod.apply_theme()


def test_select_saves_but_does_not_change_active(qtbot: QtBot):
    """選択は保存＋ステータスのみ — active()/画面は不変 (再起動反映)。"""  # noqa: RUF002
    try:
        window = build_main_window()  # 未保存 → AUTO 既定
        qtbot.addWidget(window)
        before = active()
        acts = _theme_actions(window)
        acts["ライト"].trigger()
        assert load_theme_mode() is ThemeMode.LIGHT
        assert active() is before  # 即適用しない
        assert "再起動" in window.status_message()  # 右ラベルへ移設 (spec §2.4)
        # 排他: ライトを選ぶとオートが unchecked
        assert acts["ライト"].isChecked()
        assert not acts["オート（OS に合わせる）"].isChecked()
    finally:
        set_active(DARK)
        apply_mod.apply_theme()
