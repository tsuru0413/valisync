# rendering-correctness-perf 増分1: リサイズ LOD ガード ＋ Y 軸零幅パディング 設計

**日付**: 2026-07-10
**サブスペック**: `rendering-correctness-perf`（②改善サブスペック）
**対象課題**: RN-03（リサイズ毎の全曲線 LOD 再計算）・RN-05（定数信号の零幅 Y 軸退化）
**一次情報源**: [docs/audit-findings-catalog.md](../../audit-findings-catalog.md) の RN-03 / RN-05

## 位置づけ

`rendering-correctness-perf` の残り課題 RN-03/04/05 を **2 増分**に分割したうちの**増分1**。

- **増分1（本 spec）**: RN-03（幅ガード）＋ RN-05（零幅パディング）。いずれも ViewModel 層の局所修正で低リスク・Layer A 中心。
- **増分2（別サイクル）**: RN-04（X 同期扇状展開の性能）。アーキテクチャ判断（コアレス/デバウンス vs オフスレッド）を要するため、増分1 出荷後に別途 brainstorming する。

RN-01/RN-02（描画正しさ・[2026-07-05-rendering-correctness-design.md](2026-07-05-rendering-correctness-design.md)）と RN-06（カーソル移動 perf・cursor-readout-perf 増分①）は解消済み。

## 目標

1. 高さのみのパネルリサイズで無駄な LOD 再計算を起こさない（RN-03）。
2. 定数信号（値が一定）の Y 軸を、退化した目盛りでなく可読なレンジで描く（RN-05）。

いずれも **MVVM 非変更**（View 改変なし）・**根本解決**（症状の隠蔽でない）・既存の描画/オートフィット契約を壊さない。

## アーキテクチャ概要

両修正とも `GraphPanelVM` / `YAxisVM`（純 Python ViewModel・Qt 非依存）に閉じる。View 層（`graph_panel_view.py`）は無変更で、既存の `resizeEvent`→`set_panel_width` 経路・オートフィット経路・`calculate_virtual_range` 消費経路がそのまま改善の恩恵を受ける。

LOD パイプライン（`render_data`）のキャッシュキーは `(round(x_lo), round(x_hi), panel_width_px, 可視信号キーのソート済みタプル)` で**高さ非依存**。この事実が RN-03 修正の正当性の根拠。

---

## RN-03: 高さのみリサイズでの LOD 再計算を止める

### 根本原因

`GraphPanelView.resizeEvent`（`src/valisync/gui/views/graph_panel_view.py:2114`）は幅・高さいずれの変更でも
`self.vm.set_panel_width(max(1, event.size().width()))` を呼ぶ。
`GraphPanelVM.set_panel_width`（`src/valisync/gui/viewmodels/graph_panel_vm.py:731`）は
**幅が変わっていなくても無条件で** `_invalidate_cache()`＋`_notify("range")` する。
notify → View の `refresh()` → `render_data()` → 全曲線の再スライス＋ダウンサンプル（LOD 再計算）。
キャッシュキーは高さを含まないため、高さのみリサイズ時のこの再計算は**結果が同一で純粋な無駄**。

### 修正

`set_panel_width` の先頭に幅変化ガードを追加する。

```python
def set_panel_width(self, px: int) -> None:
    # Height-only resizes call this with an unchanged width. LOD depends on
    # panel_width_px (the cache key), never on height, so re-fitting then is
    # pure waste. Bail out unless the pixel budget actually changed (RN-03).
    if px == self.panel_width_px:
        return
    self.panel_width_px = px
    self._invalidate_cache()
    self._notify("range")
```

- 幅が実際に変われば従来通り再計算（挙動不変）。
- View 側は無変更。`resizeEvent` は毎回呼び続けるが、幅不変なら VM が no-op で吸収する。
- 症状の隠蔽でなく、無駄な計算そのものを消す根本解決。

### 補足（YAGNI）

`resizeEvent` 側で「幅が変わった時だけ VM を呼ぶ」実装も可能だが、幅の真実（`panel_width_px`）は VM が持つため、ガードは VM 側が単一責務として正しい。View に幅の前回値を持たせると状態が二重化する。

---

## RN-05: 定数信号の零幅 Y 軸を可読レンジへ正規化

### 根本原因

軸のオートフィットは軸上の全信号の有限値 min/max を取る（`GraphPanelVM` の3経路: `reset_axis_y`・add-signal fit・`_auto_fit_ranges`）。
定数信号は `min == max == v` なので `axis.set_range(v, v)` となり `y_range=(v, v)`（零幅）を格納する。
`YAxisVM.calculate_virtual_range`（`src/valisync/gui/viewmodels/y_axis_vm.py:49-50`）は
`span = max(y_max - y_min, 1e-9)` で clamp する。この `1e-9` はゼロ除算回避の**対症手当て**にすぎず、
リージョンの縦ストリップに 1e-9 幅を写像した結果、pyqtgraph の目盛りが退化する（`v` 付近に潰れる／浮動小数ノイズ／有意な tick なし）。

### 解決アプローチ（採用: auto-fit 元での正規化）

零幅（または実質ゼロ幅）のデータレンジを、`v` を中心とした可読な窓へ**対称拡張**してから格納する。
正規化は**オートフィット経路のみ**に適用し、**手動レンジ指定（軸メニュー「範囲指定」= `set_y_range`）には適用しない**（ユーザー明示値を尊重）。

**配置**: 共有ヘルパを新設し、3つのオートフィット経路が確定した `(lo, hi)` を通してから `set_range` する。

```python
# graph_panel_vm.py（モジュールレベル関数。self 不要な純関数として単体テストしやすくする）
def _padded_range(lo: float, hi: float) -> tuple[float, float]:
    """Expand a degenerate (near-zero-width) auto-fit range around its centre so a
    constant signal gets a readable axis instead of 1e-9-wide degenerate ticks (RN-05).

    Applied to auto-fit results only; manual set_y_range keeps the user's exact values.
    """
    span = hi - lo
    eps = max(abs(hi), abs(lo), 1.0) * 1e-9   # relative zero-width detection
    if span > eps:
        return (lo, hi)                        # already non-degenerate: unchanged
    v = (lo + hi) / 2.0                        # == lo == hi for a constant signal
    pad = abs(v) * 0.5 if v != 0.0 else 1.0    # v!=0: +/-50% window; v==0: [-1, 1]
    return (v - pad, v + pad)
```

各オートフィット経路の `axis.set_range(lo, hi)` 直前で、`lo`/`hi` が共に非 None のとき `lo, hi = _padded_range(lo, hi)` を通す（`lo is None`= フィット対象なし の場合は従来通り `set_range(None, None)` でクリア）。

- **UX**: 定数線が窓の中央に来る。例: 1.0 張り付き → 軸 0.5–1.5・線は中央。値 0 張り付き → 軸 [-1, 1]。「平坦で v」と目盛りから読める。
- **一貫性**: 格納レンジ自体が健全になるため、軸スパインの目盛り・ラベル・`calculate_virtual_range` の写像・カーソル readout の軸文脈がすべて整合する（複数 Y 軸はリージョンベースのオーバーレイで、格納レンジが軸スパインの目盛りを駆動する）。
- `calculate_virtual_range` の `max(span, 1e-9)` clamp は**残す**（ゼロ除算に対する最後の防波堤・二重の安全）。ただし通常はもう零幅レンジが流入しない。

### 却下した代替案

`calculate_virtual_range` の内部だけで pad する案は、視覚写像は直るが**格納レンジは退化のまま**で他の消費者（tick ラベル計算等）に退化が残りうるため却下。正規化は auto-fit の源で一度だけ行い、単一の真実にする。

---

## テスト戦略（②実質性）

すべて Layer A（ViewModel 純ロジック）で実質を尽くせる。realgui は任意（軸目盛りの見た目確認は補助）。

### RN-03（弁別的なガードテスト）

`_invalidate_cache`（または `render_data` / `Session.downsample`）呼び出しをスパイし:

- `set_panel_width(現在と同じ px)` → `_invalidate_cache` が**呼ばれない**・`_notify` が**発火しない**。
- `set_panel_width(異なる px)` → **呼ばれる**・発火する（従来動作）。

ガードを削除するとテストが赤になる（false-green でない）ことを sabotage で確認。

### RN-05（正規化の正しさ）

- 定数信号（例: 全サンプル値 = 5.0）を軸に載せてオートフィット → `axis.y_range` が非退化（`hi > lo`）で中心 ≈ 5.0（例 `(2.5, 7.5)`）。
- 同状態で `calculate_virtual_range()` が健全な有限スパンを返す（1e-9 でない）。
- `v == 0` の定数信号 → `y_range == (-1.0, 1.0)`。
- **手動レンジ非 pad**: `set_y_range(3.0, 3.0)`（ユーザー明示のゼロ幅）→ pad されず `(3.0, 3.0)` のまま（`_padded_range` を通さない経路であることの確認）。
- 非退化な通常レンジ（`min != max`）→ `_padded_range` が恒等（変更しない）。

### 回帰

既存の描画・オートフィット・複数 Y 軸・カーソル readout テストが全 PASS（両修正は既存の非退化・幅変化経路の挙動を変えない）。

## 影響ファイル

- `src/valisync/gui/viewmodels/graph_panel_vm.py`（`set_panel_width` ガード・`_padded_range` ヘルパ・3オートフィット経路で適用）
- `src/valisync/gui/viewmodels/y_axis_vm.py`（変更なし想定。`calculate_virtual_range` の clamp は残置）
- テスト: `tests/gui/test_graph_panel_vm.py`（RN-03 ガード・RN-05 正規化）

## 非目標

- RN-04（X 同期扇状展開の性能）は増分2。
- LOD アルゴリズム自体・ダウンサンプラ・キャッシュキー構造は変更しない。
- 遅延ロード/メモリマップ等の大改修は対象外。
