# Y軸リージョン高さ保持（信号削除時）設計

> 発見元 follow-up: [docs/multi-axis-empty-region-followup.md](../../multi-axis-empty-region-followup.md) の **案B**。
> 関連 spec: `.kiro/specs/valisync-gui-axes/`（リージョンベース複数Y軸レイアウト）。
> 日付: 2026-06-28 / ブランチ: `feature/valisync-gui-axes-height-preserve`

## 背景

複数信号を別リージョンに表示し、ユーザーが divider をドラッグして高さ比を調整した状態（例 0.5/0.3/0.2）から信号を1つ削除すると、残った軸の高さが**等分にリセット**される。

follow-up doc の **案A**（空軸の刈り取り）は PR #10（`49086f2`）で既に解決済みで、回帰テスト `test_remove_signal_prunes_now_empty_axis` も green。本設計は残課題の **案B（ユーザー調整高さの保持）** を扱う。

## 根本原因

`GraphPanelVM._normalize_axes` が概念的に異なる2つの責務を1メソッドに束ね、その片方を**常に破壊的に適用**している：

1. **構造の整合（常に必要）**: 空軸の刈り取り、plotted entry の `axis_index` 再マッピング、全削除時の単一 placeholder への collapse。不変条件の維持。
2. **レイアウト方針（呼び出し元ごとに異なるべき）**: `top_ratio`/`height_ratio` の割り当て。

現状は (2) を常に「等分リセット」で実行するため、削除（残存軸の比率が有効なまま）でもユーザー調整高さが必ず潰される。`preserve_heights` フラグを1個足すだけの修正はこの**束ね（conflation）を温存**するため症状緩和寄り（目先優先）であり、根本改修ではない。

## 設計判断（確定済み）

| 項目 | 決定 |
|---|---|
| 再分配方式 | **比例維持**: 残存軸の現在 `height_ratio` を列内合計で正規化（相対比を保持）。例 0.5/0.3/0.2 で中央削除 → 0.5:0.2 を保って 0.714/0.286 |
| 適用範囲 | `remove_signal` **と** `prune_missing_signals` の両方 |
| アプローチ | フラグ追加ではなく**2責務を構造分離**する根本改修 |

## 設計：2責務の構造分離

`_normalize_axes` を2つの焦点を持つメソッドへ分割する。

```
_compact_axes()                        # 構造整合のみ。常に実行
    - used = 信号を持つ軸の index 集合
    - used が空 → 単一フルハイト placeholder へ collapse（既存挙動）
    - それ以外 → 空軸を刈り取り、self._axes を圧縮、plotted entry の axis_index を再マップ

_relayout_columns(*, preserve_heights) # レイアウト方針のみ。列ごとに高さ割当
    - 列ごとに top_ratio 昇順で並べ替え（縦順保持）
    - preserve_heights=False → 等分（h = 1/n）
    - preserve_heights=True  → 各軸 height = old_height / Σ(列内 height)、top を縦順に積上げ
    - Σ == 0 のゼロ除算ガード → 等分にフォールバック
```

`_normalize_axes` は**廃止する**（後方互換ラッパも残さない）。全呼び出し元が `_compact_axes()` → `_relayout_columns(...)` を**明示的に**呼ぶ。これにより各呼び出し元のコードを読むだけで「構造整合してから、等分 or 比例維持でレイアウトする」という意図が見え、隠れた挙動がなくなる。

### 呼び出し側（全 5 箇所を置換）

| 呼び出し元 | 置換後 |
|---|---|
| `create_new_axis` / `move_axis_to_column` / `set_column_count` | `_compact_axes()` → `_relayout_columns(preserve_heights=False)`（等分。意図的） |
| `remove_signal` / `prune_missing_signals` | `_compact_axes()` → `_relayout_columns(preserve_heights=True)`（比例維持） |

- `create_new_axis` は初期 placeholder の刈り取りに `_compact_axes()` が必須（既存の核心挙動）。`move_axis_to_column` / `set_column_count` では `_compact_axes()` は実質 no-op だが無害（冪等）なので一貫して両方呼ぶ。
- `_compact_axes()` が「全信号削除 → 単一 placeholder collapse」した場合でも、続く `_relayout_columns(...)` は単一軸に対し height 1.0 / top 0.0 を再代入するだけで冪等。collapse 分岐を特別扱いする必要はない。
- docstring 内の `_normalize_axes` 参照（`create_new_axis` / `move_axis_to_column`）も新メソッド名へ更新する。
- `_normalize_axes()` を直接叩く既存テスト `test_normalize_splits_height_per_column`（`tests/gui/test_graph_panel_multi_axis.py:678,686`）は `_relayout_columns(preserve_heights=False)` 直叩きへ更新する（同テストは等分レイアウトの検証であり、新メソッドで等価に表現できる）。

これにより「削除時に等分リセットが走る」経路が**構造的に存在しなくなる**（削除パスは等分方針を呼ばない）＝バグが設計で不可能になる。`preserve_heights` は残るが、もはや構造と束ねた分岐ではなく**レイアウト方針の純粋な名前**であり band-aid ではない。

### エッジケース

- **冪等**: 軸が刈られない削除（複数信号軸から1本だけ消す等）でも、列の高さは既に合計1.0なので比例正規化は no-op。「刈ったか判定」不要で常に `preserve_heights=True` を呼べる。
- **残り1軸 → 1.0**: 比例維持でも単一軸は `height_ratio==1.0`。既存 `test_remove_signal_prunes_now_empty_axis`（`==1.0`）は変更不要で green のまま。
- **列スコープ**: 比例正規化は列ごとに閉じる。ある列で削除しても他列の高さは不変。
- **全信号削除**: `_compact_axes()` の placeholder collapse がそのまま機能（保持対象なし）。

### View 層

変更不要。`_on_vm_change` → `refresh()` → `_reconcile_axes()` が通知種別に関わらず無条件に軸レイアウトを再構築する。

## 配線事実（E2E 対象の根拠）

調査の結果：

- **`GraphPanelVM.remove_signal` を呼ぶ本番コードは存在しない**（テストのみ）。グラフパネル上で信号を消す UI ジェスチャは未実装。前方互換の公開 API として保持する。
- **実際に配線された削除フロー**は: FileBrowser「Remove File」右クリック → app `"unloaded"` イベント → `graph_area_vm._on_app_change("unloaded")` → 各パネル `prune_missing_signals`（`graph_area_vm.py:64-66`）。

したがって**ユーザー操作で高さ保持が実走する経路は `prune_missing_signals` 側**であり、E2E は「ファイル削除→prune」を対象にする。`remove_signal` への Layer C は実アプリに存在しない経路の偽 E2E になるため作らない。

## テスト計画

[docs/gui-testing-layers.md](../../gui-testing-layers.md) の必須運用に従う。本変更は VM 純ロジックのため**方針表上は Layer A が必須・B/C は非該当**。ただし E2E 価値（false-green 回避）のため、配線パスの結合 E2E（Layer A/B）を必須に昇格し、実配線フロー（Remove File→prune→保持）を端まで通す Layer C を release-confidence として追加する。TDD は全レイヤー RED→GREEN。

### Layer A — VM 純ロジック（必須・CI）

`tests/gui/test_graph_panel_multi_axis.py`。`remove_signal`/`prune` は同一コア（`_compact_axes`+`_relayout_columns(preserve=True)`）を共有するため両方カバーされる。

1. `test_remove_signal_preserves_remaining_proportions` — 3軸 0.5/0.3/0.2 → 中央削除 → 0.714/0.286、top 0.0/0.714、`len==2`（`pytest.approx`）。**現状は 0.5/0.5 になるため RED**。
2. `test_remove_one_signal_from_multisignal_axis_keeps_heights` — axis0 に2信号＋axis1、0.6/0.4 → axis0 から1信号だけ削除（刈り取り無し）→ 高さ不変。冪等性保証。
3. `test_prune_missing_signals_preserves_remaining_proportions` — 3軸 0.5/0.3/0.2、`session.signals` 上書きで中央を消す（既存 prune テストのパターン）→ prune → 0.714/0.286。
4. `test_remove_preserves_proportions_per_column` — 2列。col1 に3軸 0.5/0.3/0.2、col0 に2軸 0.5/0.5 → col1 中央削除 → col1 が 0.714/0.286、col0 は 0.5/0.5 不変。列スコープ保証。
5. `test_relayout_total_zero_falls_back_to_equal` — 全 `height_ratio=0` で `_relayout_columns(preserve_heights=True)` を呼んでも ZeroDivisionError にならず等分。退避ガード（private レイアウトメソッド直叩き、既存テストと同流儀）。
6. 回帰: 既存 `test_normalize_splits_height_per_column` は呼び出しを `_relayout_columns(preserve_heights=False)` 直叩きへ更新し、等分アサーション（0.0/0.5・0.5/0.5、単独軸=1.0）は不変のまま green を維持（等分パスの回帰保証）。`test_remove_signal_prunes_now_empty_axis`（`==1.0`）は無変更で green 維持。

### Layer A/B — 決定論 結合 E2E（必須・CI）

7. `test_unload_preserves_panel_proportions` — App / GraphArea / 実 `GraphPanelView` を結線。2ファイル読込→3リージョン非等分（`resize_axis`）→ 中央信号のファイルを app から unload → `_on_app_change("unloaded")` → `prune_missing_signals` 実行 → 生存軸 0.714/0.286、かつ View 再構築後のリージョン幾何も反映、を assert。**本番配線そのもの**を CI で検証。

### Layer C — 実OS入力 E2E（追加・推奨・`--realgui`・ローカル・Windows）

8. `tests/realgui/test_remove_file_preserves_proportions.py` — 2ファイル読込・複数リージョン状態で:
   - **実マウスで divider をドラッグ**して非等分化（0.5/0.3/0.2）。divider はプレーン mouseMove ドラッグ（QDrag/OLE 非経由）のため `gui_realgui_drag_qtimer_hang` のハング問題は原理的に発生しない。
   - **実右クリックで「Remove File」**（`test_file_browser_realclick.py` の実右クリック資産を流用）。
   - 生存リージョンが比率保持していることを assert（失敗時スクショ保存）。
   - `test_multi_column_axis.py` の watchdog/スクショ harness を流用。
   - 価値: 実 divider ドラッグ→高さ永続化→実 Remove File→prune→保持、という本機能が依存する**実配線フローを端から端まで**検証し、現状未カバーの実 divider 経路の空白も閉じる。

## スコープ外

- 削除以外（add/move/列数変更）の等分挙動の変更（意図的に等分のまま）。
- 比例維持以外の再分配（隣接加算など）。

## 関連リンク

- 改修対象: `src/valisync/gui/viewmodels/graph_panel_vm.py`
- 発見元: `docs/multi-axis-empty-region-followup.md`（案B）
- 配線: `src/valisync/gui/viewmodels/graph_area_vm.py`（`_on_app_change`）, `src/valisync/gui/views/file_browser_view.py`（Remove File）
- テスト方針: `docs/gui-testing-layers.md`
- 既存 realgui 資産: `tests/realgui/test_file_browser_realclick.py`, `tests/realgui/test_multi_column_axis.py`
