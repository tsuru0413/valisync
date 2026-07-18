# アクティブパネル枠の複数プロット条件化（active-frame-multi-panel）設計

日付: 2026-07-18 ／ ステータス: 承認済み（brainstorming）
出自: UIUX 再設計プログラム増分A — claude.ai/design 検討の inbox 決定メモ
（2026-07-18-uiux-concept-and-main-layout）＋カード「コンセプトとメイン画面案」3a/4a。
分解の俯瞰はプログラム全体（A〜F 6増分）のうち最初のクイックウィン。

## 1. 背景・問題

タブ内のアクティブパネルには amber 枠（`_active_frame`・`accent_active` トークン）が
常時描かれる。パネルは「作った=使う」で自動アクティブになるため、**単一プロットの
通常利用でも枠が常時表示**され、視線を波形本体から奪う（UIUX 監査 課題C）。
1枚しかなければ「どれがアクティブか」は自明で、枠は情報を運ばない。

## 2. 要件

- タブ内のパネルが **1枚のとき: アクティブ枠を描かない**
- **2枚以上のとき: 従来どおり**アクティブパネルにのみ枠を描く
- タブごとに独立判定（各タブ1枚なら全タブで枠なし）
- **変えないもの**: アクティブパネルの追跡・配送（Add/Export はアクティブへ）、
  アクティブ**軸**の affordance（枠/グリップ — クリック時のみ表示される opt-in 動作で
  リサイズの操作入口。単一プロット時も現状維持）、`accent_active` トークン値

## 3. 実装（View 側の条件分岐・1箇所）

`GraphAreaView._sync_active_frames()`（graph_area_view.py）で判定に「タブ内パネル数」
を加える:

```python
def _sync_active_frames(self) -> None:
    for tab_index, panel_index, widget in self._panel_views:
        widget.set_panel_active(
            panel_index == self.vm.active_panel_index(tab_index)
            and len(self.vm.panels(tab_index)) >= 2
        )
```

- 枠表示は純粋に描画の関心事 → View に置き、VM の `active_panel_index` 契約は不変
  （VM プロパティ追加案は責務過剰で不採用・YAGNI）
- rebuild 後・`"active_panel"` 軽量通知の両経路が本関数を通るため1箇所で完結。
  パネル追加（1→2枚で出現）・削除（2→1枚で消滅）は rebuild 経由で自動追随

## 4. 検証

**Layer B（CI）**:
1. 単一パネル: アクティブでも `_active_frame` 非表示
2. 2パネル: アクティブのみ表示・非アクティブ非表示（既存挙動の保存）
3. 2→1枚（remove）: 枠消滅
4. 1→2枚（add）: アクティブ側に出現
5. 既存テストの fallout: PC-07 系が「単一パネルで枠表示」を前提にしていれば
   honest に更新（隠蔽・緩和で誤魔化さない）

**Layer C（realgui・/gui-verify ①ゲート）**:
- クリック活性化系の既存 realgui が単一パネル構成で枠を assert していれば新挙動へ
  更新（挙動値変更時は並行 realgui も更新 — memory
  gui_behavior_change_stale_parallel_realgui_test）
- 2パネル構成での「クリック→枠移動」実機確認＋無回帰

**成果物（意図差分）**:
- 凍結ベースライン5状態は単一パネル構成 → **02-05 から amber 枠が消える**。
  前後差分の空間分布で「枠の消滅のみ」を実証 → ベースライン差し替え・
  カタログ両テーマ再撮影・valisync-design 再同期
- docs/design.md 決定履歴へ追記（運用反復2 — 値変更なし・適用条件変更として記録・
  inbox メモを出典に）。CLAUDE.md 更新は merge 後 docs PR

## 5. 進め方

`feature/active-frame-multi-panel` ブランチ・subagent-driven development・
ゲート4種（pytest / ruff check / ruff format --check / mypy src/）。
実装1タスク＋検証/成果物タスクの小反復。
