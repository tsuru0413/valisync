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
| 保持方式 | **絶対保持＋空白ギャップ**: 生存軸は現在の `top_ratio`/`height_ratio`（パネル全体に対する絶対比率・位置）を**そのまま保持**。削除軸は**純粋な空白**（軸ごとレイアウトから除去）として残し、生存軸を再配置・再スケールしない。例 0.5/0.3/0.2 で中央削除 → A=0.5(top0.0) / 空白0.3 / C=0.2(top0.8)（合計0.7＜1.0） |
| 残り1軸 | 単一になっても絶対比率を維持（全高に拡張しない）。全信号削除時のみフルハイト placeholder へ collapse |
| 適用範囲 | `remove_signal` **と** `prune_missing_signals` の両方 |
| アプローチ | フラグ追加ではなく**2責務を構造分離**する根本改修 |

> **改訂履歴 (2026-06-28)**: 当初は「比例維持（生存軸どうしの相対比を保って全体に広げる, 0.714/0.286）」で実装したが、ユーザー意図は「各軸の**全体に対する絶対比率**を保持し、削除分は空白」だったため、**削除パスは再レイアウトを行わない**方式へ変更（`_relayout_columns` の `preserve_heights` 比例分岐は削除）。

## 設計：2責務の構造分離

`_normalize_axes` を2つの焦点を持つメソッドへ分割する。

```
_compact_axes()                        # 構造整合のみ。常に実行
    - used = 信号を持つ軸の index 集合
    - used が空 → 単一フルハイト placeholder へ collapse（既存挙動）
    - それ以外 → 空軸を刈り取り、self._axes を圧縮、plotted entry の axis_index を再マップ

_relayout_columns()                    # レイアウト方針（等分）のみ。add/move/列数変更で使用
    - 列ごとに top_ratio 昇順で並べ替え（縦順保持）
    - 各軸 height = 1/n（列内等分）、top を縦順に積上げ
    - 削除パスは呼ばない（生存軸の絶対比率を保持するため）
```

`_normalize_axes` は**廃止する**（後方互換ラッパも残さない）。各呼び出し元が必要な操作を**明示的に**呼ぶ。これにより「構造整合してから（必要なら）等分レイアウトする」意図がコードに現れ、隠れた挙動がなくなる。

### 呼び出し側

| 呼び出し元 | 置換後 |
|---|---|
| `create_new_axis` / `move_axis_to_column` / `set_column_count` | `_compact_axes()` → `_relayout_columns()`（等分。意図的） |
| `remove_signal` / `prune_missing_signals` | `_compact_axes()` **のみ**（再レイアウトしない＝生存軸の絶対比率を保持、削除軸は空白） |

- `create_new_axis` は初期 placeholder の刈り取りに `_compact_axes()` が必須（既存の核心挙動）。`move_axis_to_column` / `set_column_count` では `_compact_axes()` は実質 no-op だが無害（冪等）。
- 削除パスは `_compact_axes()` のみ。`_compact_axes` は生存軸の `top_ratio`/`height_ratio` を変更しないため、削除軸の帯はそのまま空白になり、生存軸は動かない。全信号削除時は `_compact_axes` がフルハイト placeholder へ collapse する。
- docstring 内の `_normalize_axes` 参照（`create_new_axis` / `move_axis_to_column`）も新メソッド名へ更新する。
- `_normalize_axes()` を直接叩く既存テスト `test_normalize_splits_height_per_column` は `_relayout_columns()` 直叩きへ更新する（等分レイアウトの検証）。

これにより「削除時に再レイアウトが走る」経路が**構造的に存在しなくなる**（削除パスはレイアウト方針を一切呼ばない）＝等分リセットも比例フィルも起きず、生存軸は必ず絶対比率のまま残る。

### エッジケース

- **軸が刈られない削除**（複数信号軸から1本だけ消す等）: `_compact_axes` は何も刈らず比率も触らないので高さは完全に不変。
- **残り1軸**: 単一になっても絶対比率を維持（例 0.2 のまま、残りは空白）。**既存 `test_remove_signal_prunes_now_empty_axis` は `==1.0`（全高化）を期待していたため新挙動（生存軸は元の絶対値）へ更新する**（PR #10 の挙動を置き換え）。
- **列スコープ**: `_compact_axes` は全列横断で空軸を刈るだけで比率を触らないため、他列も含め生存軸はすべて絶対比率のまま。
- **全信号削除**: `_compact_axes()` の placeholder collapse がそのまま機能（フルハイト placeholder）。

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

`tests/gui/test_graph_panel_multi_axis.py`。`remove_signal`/`prune` は同一コア（`_compact_axes` のみ）を共有するため両方カバーされる。

1. `test_remove_signal_keeps_absolute_heights_with_blank_gap` — 3軸 0.5/0.3/0.2 → 中央削除 → A(top0.0,h0.5)/C(top0.8,h0.2)、`len==2`、高さ合計0.7（空白0.3）。
2. `test_remove_one_signal_from_multisignal_axis_keeps_heights` — axis0 に2信号＋axis1、0.6/0.4 → axis0 から1信号だけ削除（刈り取り無し）→ 高さ不変。
3. `test_prune_missing_signals_keeps_absolute_heights_with_blank_gap` — 3軸 0.5/0.3/0.2、`session.signals` 上書きで中央を消す → prune → A(0.0,0.5)/C(0.8,0.2)、合計0.7。
4. `test_remove_keeps_absolute_heights_per_column` — 2列。col1 に3軸 0.5/0.3/0.2、col0 に2軸 0.5/0.5 → col1 中央削除 → col1 が (0.0,0.5)/(0.8,0.2)、col0 は (0.0,0.5)/(0.5,0.5) 不変。列スコープ保証。
5. `test_remove_signal_prunes_now_empty_axis`（既存・更新）— 2軸 0.5/0.5 → 上を削除 → 生存軸は top0.5/h0.5 のまま（**1.0 ではない**）、上半分は空白。PR #10 の全高化を置き換え。
6. 回帰: `test_normalize_splits_height_per_column` は `_relayout_columns()` 直叩きへ更新し、等分アサーション（0.0/0.5・0.5/0.5、単独軸=1.0）は不変のまま green（等分パスの回帰保証）。

### Layer A/B — 決定論 結合 E2E（必須・CI）

7. `test_unload_preserves_panel_proportions` — App / GraphArea / 実 `GraphPanelView` を結線。3ファイル読込→3リージョン非等分（0.5/0.3/0.2）→ 中央ファイルを app から unload → `_on_app_change("unloaded")` → `prune_missing_signals` 実行 → 生存軸 A(0.0,0.5)/C(0.8,0.2)（合計0.7・空白あり）、View が 2 ViewBox に再構築、を assert。**本番配線そのもの**を CI で検証。

### Layer C — 実OS入力 E2E（追加・推奨・`--realgui`・ローカル・Windows）

8. `tests/realgui/test_remove_file_preserves_proportions.py` — 2ファイル読込・複数リージョン状態で:
   - **実マウスで divider をドラッグ**して非等分化（0.5/0.3/0.2）。divider はプレーン mouseMove ドラッグ（QDrag/OLE 非経由）のため `gui_realgui_drag_qtimer_hang` のハング問題は原理的に発生しない。
   - **実右クリックで「Remove File」**（`test_file_browser_realclick.py` の実右クリック資産を流用）。
   - 生存リージョンが**絶対高さを保持**（削除帯は空白）していることを assert（失敗時スクショ保存）。
   - watchdog（ESC+ボタン解放）/ faulthandler / ウィンドウ最前面化 / モーダルメニューの `QEventLoop`+`singleShot` 捕捉で、非対話環境でもハングせず実機自動実行可能。
   - 価値: 実 divider ドラッグ→高さ永続化→実 Remove File→prune→絶対保持、という本機能が依存する**実配線フローを端から端まで**検証。実機で PASS 確認済み。

## スコープ外

- 削除以外（add/move/列数変更）の等分挙動の変更（意図的に等分のまま）。
- 比例維持以外の再分配（隣接加算など）。

## 関連リンク

- 改修対象: `src/valisync/gui/viewmodels/graph_panel_vm.py`
- 発見元: `docs/multi-axis-empty-region-followup.md`（案B）
- 配線: `src/valisync/gui/viewmodels/graph_area_vm.py`（`_on_app_change`）, `src/valisync/gui/views/file_browser_view.py`（Remove File）
- テスト方針: `docs/gui-testing-layers.md`
- 既存 realgui 資産: `tests/realgui/test_file_browser_realclick.py`, `tests/realgui/test_multi_column_axis.py`
