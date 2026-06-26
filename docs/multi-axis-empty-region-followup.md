# 多軸レイアウト 空リージョン残存 改善メモ

> 関連 spec (発見元): `valisync-gui-axes` (PR #4 / #5 で完了)。
> 発見の経緯: 「チャンネルブラウザから**最初の信号**を D&D するとハーフハイトになる」不具合の根本調査中、同じ「**空軸がパネル領域を占有する**」問題が**信号削除**でも起きると判明した。最初の D&D 側は別 PR で根本対処済み (`GraphPanelVM._normalize_axes` を `create_new_axis` に適用)。本メモは削除側の未対応分を記録する。

## 現象

複数信号を別リージョンに表示した状態から1つを削除すると、その軸が**空のまま領域 (height_ratio) を占有し続ける**。結果、残った信号がパネル全高ではなくハーフハイト等で表示され、隣に空白リージョンが残る。

再現 (純VM):
```
A,B の2信号 → 2リージョン (各0.5)
remove A → axis[0] h=0.500 (EMPTY) / axis[1] B h=0.500   ← B はハーフのまま
```

## Spec 上の評価

- 本 spec (`valisync-gui-axes`) のコア要件 (多軸オーバーレイ / Auto-Fit / リージョン分割) は満たしており、本件は**スコープ外の改善余地**。
- 「最初の D&D フルハイト」修正と同じ根本原因 (`_normalize_axes` 不適用) の別経路にすぎないため、**単純な後追い** (小規模) で対応可能。即 spec 化せず follow-up として蓄積する。

## 原因

`GraphPanelVM.remove_signal` は `self._plotted` から該当エントリを除くだけで `self._axes` を一切触らない。レイアウトは「軸の本数」で縦を分割するため、信号0本になった軸も領域を保持する。最初の D&D 側は `create_new_axis` 末尾で `_normalize_axes` を呼んで空軸を刈り取るようにしたが、`remove_signal` は未適用。

## 改善案 (複数)

- **案A (簡素)**: `remove_signal` の末尾で `self._normalize_axes()` を呼ぶ。空軸を刈り取り、残った軸で**等分**再分配する。`_normalize_axes` は実装済みなので追加は1行に近い。
- **案B (丁寧)**: ユーザーが divider で調整した高さを尊重し、削除された軸の領域だけを隣接 (または全体に比例) 再配分する。`_normalize_axes` の等分ロジックを「比例維持」版に分岐させる。

## 採用方針 (推奨)

- 後追い対応として、まず**案A** を適用するのが妥当 (挙動が「最初の D&D フルハイト」修正と対称になり、`_normalize_axes` を素直に再利用できる)。
- 高さ保持 (案B) を求める声が出たら拡張する。spec 化が必要なほどの規模ではない見込み。
- 着手タイミング: 次に多軸レイアウト周りを触る際、または利用者から空白リージョンのフィードバックが届いた時。

## 関連リンク

- 改修対象: `src/valisync/gui/viewmodels/graph_panel_vm.py` — `remove_signal` / `_normalize_axes`
- 既存テスト: `tests/gui/test_graph_panel_multi_axis.py` (TestContextualDrop / TestMultiAxisLayout), `tests/gui/test_graph_panel_view.py` (TestDrop)
- 対称な対処済み経路: `create_new_axis` → `_normalize_axes`
