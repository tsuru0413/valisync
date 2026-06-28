# Y軸リージョン高さ保持（移動・並べ替え時）設計

> 前段: [docs/superpowers/specs/2026-06-28-y-axis-height-preserve-design.md](2026-06-28-y-axis-height-preserve-design.md)（削除時の絶対保持＝PR #14 で実装済み）。
> 発見元: [docs/multi-axis-empty-region-followup.md](../../multi-axis-empty-region-followup.md)。
> 関連 spec: `.kiro/specs/valisync-gui-axes/`（リージョンベース複数Y軸レイアウト）。
> 日付: 2026-06-28 / ブランチ: `worktree-axes-move-height-preserve`

## 背景

削除（信号削除 / Remove File）時の高さ保持は **PR #14（案B）** で実装済み：生存軸は **絶対比率（パネル全体に対する高さ・位置）を保持**し、除去された軸の帯は**空白**として残す（再レイアウトしない）。

本設計はこれを **軸の移動（列またぎ）と同列内の並べ替え** へ拡張する。現状、`GraphPanelVM.move_axis_to_column` は末尾で無条件に `_relayout_columns()`（列内等分）を呼ぶため、**同列並べ替えでも列またぎ移動でも、関係する列の高さが等分にリセットされる**。ユーザーが divider で調整した高さ比が移動のたびに失われる。

## 統一原理（確定）

削除・移動・並べ替えを**1つの原理**で統一する：

> **収まるなら絶対値を保持。除去された帯は空白として残す。超過するときだけ、その列の全軸を高さ合計で割って 1.0 に収める。**

| 経路 | 挙動 |
|---|---|
| 削除 / Remove File（既存・変更なし） | 生存軸は絶対保持、除去帯は空白（面積が減るので超過しない＝常に絶対保持） |
| 同列内の並べ替え | 各軸の `height_ratio` を保持し、縦順のみ変更（面積不変＝割らない） |
| 列またぎ・移動元の列 | 抜けた軸の帯は**空白**（生存軸は絶対保持・reflow しない＝削除と同じ） |
| 列またぎ・移動先の列（収まる: 合計 ≤ 1.0） | **高さ保持・割らない**（各軸の高さは不変。移動軸は元の高さで挿入位置に入り、その分だけ挿入位置より下の軸が押し下がる。余りは最下部の空白） |
| 列またぎ・移動先の列（超過: 合計 > 1.0） | その列の**全軸を合計で割って 1.0 に縮小**（相対比は維持・絶対値は縮む） |
| 最後の信号を削除（全軸が空）（既存・変更なし） | 全高プレースホルダ1枚へ collapse（次のドロップ先） |
| 軸追加 `create_new_axis` / 列数変更 `set_column_count`（変更なし） | 列内等分（`_relayout_columns`）のまま＝意図的にスコープ外 |

「超過時に絶対値を保持」は原理的に不可能（合計が 1.0 を超え必ず誰かが縮む）。選べるのは「誰がどう縮むか」だけで、**最も予測しやすい一律縮小（合計で割る）**を採る。閾値による挙動の急変（段差）を作らない。

> **「保持」の定義**: ここでの保持は各軸の**高さ（`height_ratio`）を縮尺しない**ことを指す。軸の挿入時は、挿入位置より下の軸が移動軸の高さ分だけ押し下がる（top は積み直す）。位置まで完全固定するのは「移動元の列」と「削除」だけ（そちらは軸を**touch しない**ため絶対位置も保たれ、抜けた帯がそのまま空白になる）。

## 現状の根本原因

`move_axis_to_column` は移動軸の `column` と `top_ratio` を更新したのち、`_compact_axes()` + **`_relayout_columns()`** を呼ぶ。`_relayout_columns()` は**列ごとに高さを等分（`h = 1/n`）**するため、移動に伴って関係する列の高さが必ずリセットされる。これは「構造整合（空軸の刈り取り）」と「レイアウト方針（等分）」のうち後者を移動でも常に適用してしまっていることが原因。削除側は PR #14 で既に「`_compact_axes()` のみ・等分を呼ばない」に分離済みだが、**移動側は等分のまま**残っている。

## 設計：高さ保持レイアウトの導入

等分用の `_relayout_columns()` はそのまま残し（`create_new_axis` / `set_column_count` が使用）、移動専用に**高さを保持し超過時のみ縮小する列レイアウト**を追加する。

```
_layout_column_preserving(axes_in_vertical_order: list[YAxisVM]) -> None
    # 1列分の軸を「上から縦順に積む」。高さは保持。合計が 1.0 を超える時だけ縮小。
    total = sum(a.height_ratio for a in axes_in_vertical_order)
    if total > 1.0:
        scale = 1.0 / total
        for a in axes_in_vertical_order:
            a.height_ratio *= scale            # 相対比を保ったまま 1.0 に収める
    cursor = 0.0
    for a in axes_in_vertical_order:           # 縦順に top を積み上げ
        a.top_ratio = cursor
        cursor += a.height_ratio
    # total < 1.0 のときは縮小せず、余り (1.0 - total) は最下部の空白として残る
```

### `move_axis_to_column` の再構成

```
1. axis_index が範囲外なら no-op（ドラッグ中の stale index 対策・現状維持）
2. column = clamp(column, 0, column_count-1)
3. moved = self._axes[axis_index]; src_col = moved.column
4. moved.column = column
5. dest_order = （column 内の moved 以外の軸を top_ratio 昇順に）並べ、position に moved を挿入
6. _layout_column_preserving(dest_order)      # 移動先列のみ再計算
       - 同列並べ替え（src_col == column）: 合計は元のまま（≤1.0）→ 縮小なし＝高さ保持・縦順のみ変更
       - 列またぎ: 合計 ≤1.0 → 高さ保持（割らない・余りは下部空白） / >1.0 → 合計で割る
7. 移動元の列（src_col != column のときのみ存在）: 何もしない
       → 生存軸は top_ratio/height_ratio をそのまま保持 → 抜けた帯が空白になる
8. self._notify("axes")
```

- **`_relayout_columns()`（等分）は移動からは呼ばない。** これで「移動で等分リセットが走る」経路が構造的に消える。
- 移動軸は**自分の `height_ratio` を持ち運ぶ**（手順5で挿入時に height は変えない）。これにより「収まる」場合は元の高さのまま入り、（軸が連続配置のレイアウトでは）移動して戻すと元レイアウトに復元できる（可逆性）。
- 移動は軸を空にしないため `_compact_axes()` は実質 no-op。不変条件（空軸を残さない）維持のために呼んでも害はないが、移動の本質的なレイアウトは `_layout_column_preserving` が担う。

### エッジケース

- **同列並べ替えで列に空白があった場合**: 高さは保持しつつ軸を上から積み直すため、途中の空白は**最下部に寄る**（repack）。これは許容仕様とする（位置までは保持しない）。
- **空の列へ移動**: 移動先に既存軸が無ければ、移動軸は元の高さのまま単独で入り、余り `1.0 - height` は空白（全高には広げない＝絶対保持の一貫）。
- **移動先が満杯（合計=1.0）へ移動**: 必ず超過するので合計で割って一律縮小（図④のケース）。
- **削除 / Remove File**: 変更しない。`remove_signal` / `prune_missing_signals` は引き続き `_compact_axes()` のみで絶対保持＋空白。**移動リファクタでこの挙動を壊さないこと**を回帰テストで保証する。
- **最後の信号削除**: 変更しない（`_compact_axes` の全高プレースホルダ collapse のまま）。

### View 層

変更不要。`_on_vm_change` → `refresh()` → `_reconcile_axes()` が通知種別に関わらず `top_ratio`/`height_ratio`/`column` から軸レイアウトを無条件に再構築する。

## 配線事実（E2E 対象の根拠）

- `move_axis_to_column` の実 UI ジェスチャは **軸移動ドラッグ&ドロップ**（PR #13 / R5）。`GraphPanelView` の drop → `move_axis_to_column` に到達する。
- 実 OS ドラッグの Layer C 資産が既にある: `tests/realgui/test_multi_column_axis.py::test_axis_drag_from_inner_column_to_outer_column`（WM_LBUTTONUP → `dropEvent` → `move_axis_to_column(0, 0)`）。本設計の高さ保持アサートはここに追加できる。
- D&D の実配送経路は合成 `sendEvent` で再現不可（既知: `gui_drag_drop_not_sendevent_reproducible`）。したがって移動ドロップの実経路検証は Layer C のみ、ロジックは Layer A の直接呼び出しで検証する。

## テスト計画

[docs/gui-testing-layers.md](../../gui-testing-layers.md) に従う。本変更は VM 純ロジックのため**方針表上は Layer A が必須**、Layer C は release-confidence として推奨。TDD で RED→GREEN。

### Layer A — VM 純ロジック（必須・CI）

`tests/gui/test_graph_panel_multi_axis.py`：

1. `test_reorder_within_column_keeps_heights` — 同列 0.6/0.4 を上下入替 → 高さ 0.6/0.4 のまま縦順だけ反転（**0.5/0.5 にしない**）。
2. `test_cross_column_move_fits_keeps_heights` — 移動先に空白があり収まる（合計≤1.0）→ 移動軸は元の高さで入る・移動先既存の各軸の高さは不変（挿入位置より下は押し下げ）・余りは下部空白、移動元は抜けた帯が空白。
3. `test_cross_column_move_overflow_divides_by_sum` — 移動先が満杯へ移動（合計>1.0）→ 移動先の全軸が合計で割られ 1.0（相対比維持）、移動元は空白。
4. `test_move_into_empty_column_keeps_height` — 空の列へ移動 → 移動軸は元の高さ＋余り空白（全高化しない）。
5. 回帰更新 — 等分を期待していた既存の移動テストを保持挙動へ更新。
6. 回帰ガード — `test_prune_missing_signals_keeps_absolute_heights_with_blank_gap`（既存）が引き続き green（移動リファクタが Remove File の空白保持を壊さないこと）。
7. 回帰 — `test_normalize_splits_height_per_column`（`_relayout_columns` 直叩き＝追加/列数変更の等分）が不変で green。

### Layer C — 実OS入力 E2E（推奨・`--realgui`・ローカル・Windows）

8. `tests/realgui/test_multi_column_axis.py` を拡張（または姉妹テスト追加）— 非等分状態を作ってから**実マウスで軸を別列へドラッグ**し、移動先が保持/分割ルールに従い（等分でない）、移動元に空白が残ることを assert（失敗時スクショ）。既存の実OSドラッグ資産＋watchdog/faulthandler/最前面化の枠組みを流用。

## スコープ外

- `create_new_axis` / `set_column_count` の等分挙動（意図的に等分のまま）。
- 最後の信号削除時の全高プレースホルダ（維持）。
- 並べ替え時の途中空白の位置保持（最下部 repack で良しとする）。
- 削除 / Remove File の挙動変更（既存の絶対保持＋空白を維持するのみ）。

## 関連リンク

- 改修対象: `src/valisync/gui/viewmodels/graph_panel_vm.py`（`move_axis_to_column`、新 `_layout_column_preserving`）
- 前段設計: `docs/superpowers/specs/2026-06-28-y-axis-height-preserve-design.md`（削除時・案B）
- 配線: `src/valisync/gui/views/graph_panel_view.py`（軸移動 drop）, `tests/realgui/test_multi_column_axis.py`（実OSドラッグ）
- テスト方針: `docs/gui-testing-layers.md`
- 発見元 follow-up: `docs/multi-axis-empty-region-followup.md`
