"""theme/export.py — css/json ビルダー (Layer A・純粋関数・決定性)。"""

from __future__ import annotations

import json

from valisync.gui.theme import export
from valisync.gui.theme.tokens import DARK


def test_css_var_name_kebab_and_index():
    assert (
        export.css_var_name("color", "plot_background") == "--vs-color-plot-background"
    )
    assert (
        export.css_var_name("color", "signal_palette", 3)
        == "--vs-color-signal-palette-3"
    )
    assert (
        export.css_var_name("spacing", "chip_grid_hspace")
        == "--vs-spacing-chip-grid-hspace"
    )


def test_build_css_contains_all_color_fields_and_values():
    css = export.build_css(DARK)
    assert css.startswith(":root {")
    assert css.endswith("}\n")
    # 色: Color.css() 形式 (alpha 0-1)
    assert "--vs-color-plot-background: rgba(0,0,0,1.000);" in css
    assert "--vs-color-surface-chip: rgba(17,17,27,0.902);" in css
    # palette 10 本が index 付きで展開される
    for i in range(10):
        assert f"--vs-color-signal-palette-{i}: rgba(" in css
    # spacing/radii/typography/grid_alpha
    assert "--vs-spacing-chip-margins: 6px 5px 6px 5px;" in css
    assert "--vs-spacing-chip-vspace: 3px;" in css
    assert "--vs-radius-chip: 5px;" in css
    assert "--vs-radius-active-frame: 2px;" in css
    assert "--vs-font-small: 9px;" in css
    assert "--vs-grid-alpha: 60;" in css


def test_build_css_is_deterministic():
    assert export.build_css(DARK) == export.build_css(DARK)


def test_build_json_roundtrips_all_tokens():
    data = json.loads(export.build_json(DARK))
    # 全色フィールドが hex/css/rgba を持つ
    assert data["colors"]["cursor_a"]["hex"] == "#f9e2af"
    assert data["colors"]["surface_chip"]["rgba"] == [17, 17, 27, 230]
    assert len(data["colors"]["signal_palette"]) == 10
    assert data["colors"]["signal_palette"][0]["hex"] == "#1f77b4"
    assert data["spacing"]["chip_margins"] == [6, 5, 6, 5]
    assert data["radii"]["chip"] == 5
    assert data["typography"]["small_px"] == 9
    assert data["grid_alpha"] == 60


def test_build_json_is_deterministic_and_sorted():
    s = export.build_json(DARK)
    assert s == export.build_json(DARK)
    assert s.endswith("\n")
    data = json.loads(s)
    assert list(data["colors"].keys()) == sorted(data["colors"].keys())


def test_export_module_is_qt_free():
    import subprocess
    import sys

    code = (
        "import sys; import valisync.gui.theme.export; "
        "bad = [m for m in sys.modules if m.startswith(('PySide6', 'pyqtgraph'))]; "
        "sys.exit(1 if bad else 0)"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_inject_tokens_css_replaces_placeholder_and_fails_loudly():
    import pytest

    out = export.inject_tokens_css("<html><!-- @TOKENS_CSS --><body/></html>", DARK)
    assert "<style>" in out and "--vs-color-cursor-a" in out
    assert "@TOKENS_CSS" not in out
    with pytest.raises(ValueError):
        export.inject_tokens_css("<html>no placeholder</html>", DARK)


def test_build_token_cards_structure():
    cards = export.build_token_cards(DARK)
    assert set(cards) == {
        "tokens/colors.html",
        "tokens/spacing.html",
        "tokens/typography.html",
    }
    for path, html in cards.items():
        first_line = html.splitlines()[0]
        assert first_line == '<!-- @dsCard group="Tokens" -->', path
        assert "<!doctype html>" in html
        assert "@TOKENS_CSS" not in html  # 注入済み
    colors = cards["tokens/colors.html"]
    # 全色フィールド名が見本に載る (palette は index 付き)
    assert "cursor_a" in colors and "signal_palette-0" in colors
    assert "var(--vs-color-cursor-a)" in colors


def test_design_card_templates_follow_conventions():
    """design/cards/*.html: マーカー1行目・プレースホルダ必須・生 hex 禁止 (var(--vs-*) のみ)。"""
    import re
    from pathlib import Path

    cards_dir = Path(__file__).resolve().parents[2] / "design" / "cards"
    templates = sorted(cards_dir.glob("*.html"))
    assert templates, "design/cards/ にテンプレートが無い"
    # 全 var(--vs-*) 参照が build_css の実在変数であること (typo は無言の透明化になる)
    known = set(re.findall(r"--vs-[\w-]+", export.build_css(DARK)))
    for path in templates:
        text = path.read_text(encoding="utf-8")
        assert text.splitlines()[0] == '<!-- @dsCard group="Components" -->', path.name
        assert "<!-- @TOKENS_CSS -->" in text, path.name
        # 生 hex/rgba 禁止 — 色は必ず var(--vs-*) 経由 (トークン変更に自動追従させる)。
        # OS 既定 chrome の再現用グレーのみ 3桁 hex (#eee 等) を許容。
        assert not re.search(r"#[0-9a-fA-F]{6}\b|rgba?\(", text), path.name
        # テンプレート内の全 var(--vs-*) 参照が known に存在すること
        used = set(re.findall(r"var\((--vs-[\w-]+)\)", text))
        assert used, path.name  # テンプレートは最低1つはトークンを参照する
        assert used <= known, (path.name, sorted(used - known))
        # 注入が通ることも検証
        out = export.inject_tokens_css(text, DARK)
        assert "--vs-color-plot-background" in out


def test_build_ground_truth_card_embeds_png_as_data_uri():
    png = b"\x89PNG\r\n\x1a\nfakebytes"
    html = export.build_ground_truth_card("02_plotted", png)
    assert html.splitlines()[0] == '<!-- @dsCard group="Ground Truth" -->'
    assert "data:image/png;base64," in html
    import base64

    assert base64.b64encode(png).decode("ascii") in html
    assert "02_plotted" in html


def test_build_manifest_records_sha_hash_and_paths():
    import hashlib

    tokens_json = export.build_json(DARK)
    html = export.build_manifest(
        "abc1234", tokens_json, ["cards/readout_chip.html", "tokens/colors.html"]
    )
    assert html.splitlines()[0] == '<!-- @dsCard group="Meta" -->'
    assert "abc1234" in html
    assert hashlib.sha256(tokens_json.encode("utf-8")).hexdigest() in html
    assert "cards/readout_chip.html" in html


def test_cli_writes_full_bundle(tmp_path):
    """CLI の統合テスト — 一時 out dir へ全成果物を決定的に出力する。"""
    import subprocess
    import sys
    from pathlib import Path

    shots = tmp_path / "shots"
    shots.mkdir()
    (shots / "01_welcome.png").write_bytes(b"\x89PNG\r\n\x1a\nx")
    out = tmp_path / "export"
    repo = Path(__file__).resolve().parents[2]
    cmd = [
        sys.executable,
        str(repo / "scripts" / "export_design_tokens.py"),
        "--out",
        str(out),
        "--screenshots",
        str(shots),
        "--sha",
        "deadbee",
    ]
    # 陳腐化ファイル(改名/削除された旧出力を模擬) — purge が掃除することを後で検証する。
    stale = out / "cards" / "stale_old_card.html"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("old", encoding="utf-8")
    r1 = subprocess.run(cmd, capture_output=True, text=True)
    assert r1.returncode == 0, r1.stderr
    assert not stale.exists()  # purge が陳腐化カードを掃除する (Fix 1)
    for rel in [
        "tokens.css",
        "tokens.json",
        "tokens/colors.html",
        "tokens/spacing.html",
        "tokens/typography.html",
        "cards/readout_chip.html",
        "cards/affordances.html",
        "cards/error_states.html",
        "ground_truth/01_welcome.html",
        "meta/manifest.html",
    ]:
        assert (out / rel).is_file(), rel
    # 決定性: 再実行でバイト同一
    before = {p: p.read_bytes() for p in out.rglob("*.html")}
    r2 = subprocess.run(cmd, capture_output=True, text=True)
    assert r2.returncode == 0
    assert before == {p: p.read_bytes() for p in out.rglob("*.html")}
    # cards は注入済み (プレースホルダが残っていない)
    card = (out / "cards" / "readout_chip.html").read_text(encoding="utf-8")
    assert "@TOKENS_CSS" not in card and "--vs-color-surface-chip" in card


def test_build_css_covers_every_token_field():
    """全カテゴリの全フィールドが CSS に載る (新フィールドの無言脱落ガード)。

    typography は特例命名 (--vs-font-small) のため『フィールド数ぶんの --vs-font-* 行』
    で検証する — 新フィールド追加時に build_css 側の対応漏れがここで RED になる。
    """
    import dataclasses

    css = export.build_css(DARK)
    for f in dataclasses.fields(DARK.colors):
        if f.name == "signal_palette":
            for i in range(len(DARK.colors.signal_palette)):
                assert export.css_var_name("color", f.name, i) + ":" in css
        else:
            assert export.css_var_name("color", f.name) + ":" in css
    for f in dataclasses.fields(DARK.spacing):
        assert export.css_var_name("spacing", f.name) + ":" in css
    for f in dataclasses.fields(DARK.radii):
        assert export.css_var_name("radius", f.name) + ":" in css
    assert css.count("--vs-font-") == len(dataclasses.fields(DARK.typography))
    assert "--vs-grid-alpha:" in css
