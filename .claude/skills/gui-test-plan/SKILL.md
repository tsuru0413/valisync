---
name: gui-test-plan
description: Use when PySide6/pyqtgraph の GUI 入力経路機能のテストを計画/レビューするとき（writing-plans 中、または tasks.md の監査時）。レイヤー（A/B/C）判定や、realgui を含む実経路でしか証明できない実質的な受け入れ要件の設計が要る場面。
---

# gui-test-plan — GUI テスト戦略＆実質的受け入れ要件（課題②対策）

GUI タスクごとに「どのレイヤーをどう書くか」と「実経路でしか証明できない**実質的な**受け入れ要件」を設計し、writing-plans が織り込める**分析ブロック**を返す（非破壊。プランの所有は writing-plans）。

`docs/gui-testing-layers.md`（必須運用表・②実質性ルール・①証拠ゲート）を **enforce** する。出力形式は `reference/output-template.md`。

## 入力
spec 名 / `tasks.md` / writing-plans の下書きプラン / 自由記述のタスク。

## 手順（タスクごと）

1. **変更種別を分類**: VM/純ロジック | ウィジェット構成・状態 | 入力イベント→ハンドラ。
2. **必要レイヤー判定**（`docs/gui-testing-layers.md` の必須運用表）: A 必須 / B 要否 / C 要否＋根拠。
3. **入力経路の再現可否**: `sendEvent` で実経路再現可（`QContextMenuEvent` 等）か、**Layer C 専用**（`QDrag` D&D は合成イベントで配送不可）か。新規/不明な経路は「**手法を確立せよ**」とフラグし `.claude/skills/gui-verify/reference/realgui-recipe.md` へ誘導。
   - **realgui の掴み点はゾーン境界からマージンを取り、マジック比率でなくゾーン幾何から導出する**。掴み点が move/QDrag ゾーンへ誤侵入すると assert 失敗ではなく**ハング**になる（実例: pan テストの `spine.width()*0.10` が frame 3→8px 拡幅で move 帯に侵入しハング）。
   - **ゾーン境界を動かす変更**（frame 幅・grip 寸法・軸幅 等）には「**既存 realgui の全掴み点を再監査せよ**」を分析ブロックに必ず出す（後追い破綻防止）。
4. **②実質性ルーブリック適用**: 「人間が何を見て合格と判断するか」を列挙→各項目を「自動アサート可（`activePopupWidget()`・可視/ジオメトリ・要素数）」か「視覚（スクショ＋`/verify` 観測）」に割当。**スクショ保存だけ・VM 再チェックだけは naive としてフラグ**。
5. **受け入れ要件 Red/Green/Verify**: Verify 段は `/run`・`/verify` がそのまま食える観測チェックリスト（起動 `uv run valisync` ＋手順＋観測項目）。
6. **①証拠ゲート仕様**: 「該当 realgui を scoped 実行＋証拠添付」を**必須チェックボックス**としてプランに埋める仕様を出す（実行は `/gui-verify`）。
7. **honest layering note**: 経路を実検証しない近道（ハンドラ直叩きを Layer B と誤称する等）を明示。

## ノイジーな調査の委譲（任意）
似た既存入力経路テストの走査・再利用パターン抽出は `gui-test-strategist` サブエージェントに dispatch し、**結論だけ**受け取る（計画コンテキストを汚さない）。単純ケースはスキル内で完結。

## 出力
`reference/output-template.md` に従い、タスクごとの分析ブロックを返す。非 GUI タスクは「Layer A のみ・realgui 不要・標準 Red/Green」と返す。
