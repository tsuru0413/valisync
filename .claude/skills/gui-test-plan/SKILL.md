---
name: gui-test-plan
description: Use when planning tests for a PySide6/pyqtgraph GUI feature or any user-facing change (widgets, plots, docks, filters, drag-and-drop, perf, rendering) — before implementing. Also when a task touches src/valisync/gui/ and you need to decide what proves it works for a real user at real scale.
---

# gui-test-plan — 十分な E2E 検証を設計する（課題②対策）

GUI 変更ごとに「**十分な E2E 検証**とは何か」をタスク単位で設計し、writing-plans が織り込める**分析ブロック**を返す（非破壊・プランの所有は writing-plans）。

**核心**: FU-01〜17 は「headless は緑だが、実アプリを実スケールで操作していないので見えなかった」。真面目に回しても不十分な E2E を防ぐため、**十分な E2E の必須構成要素を設計で規定する**（禁止形でなく positive な設計）。

**REQUIRED BACKGROUND:** `reference/e2e-model.md`（E2E スペクトル・レイヤー A/B/C・入力の出所判定・②実質性・計画関連 false-green 落とし穴の権威リファレンス）。

## 十分な E2E の必須構成要素（`reference/e2e-model.md` 参照）
1. **ジャーニー同定**（diff でなくユーザー視点）。
2. **効果ごとに E2E タイプ＋実 observable**（入力=realgui スクショ／perf=**prod スケール実測**／描画=**スクショ**）。
3. **prod スケール必須**（perf/描画・`prod_demo.mf4` 330k。小データは FU-11/12/16 を隠す）。
4. **observable はユーザーが実際に見る終状態**（嘘プロキシ＝`isVisible`/`setText`1回/小データ perf を使わない）。
5. **カバレッジ完全性**（変更挙動を実経路で exercise。同名別コードは不可）。

## 手順（タスクごと）
1. **変更種別を分類**: VM/純ロジック | ウィジェット構成・状態 | 入力イベント→ハンドラ | perf | 描画。
2. **触れるユーザージャーニー**を特定（開く→ブラウズ→フィルタ→プロット→解析→閉じる のどの区間か）。
3. **E2E 受け入れを設計**: ユーザー可視の各効果に E2E タイプ＋実 observable＋prod スケール要否を割当。
4. **レイヤー判定**（`reference/e2e-model.md` 必須運用表）: A 必須／B 要否／入力経路 E2E(C)・perf E2E・描画 E2E の要否＋根拠。
5. **②実質性割当**: 「人間が何を見て合格と判断するか」→自動アサート可／視覚・実測 に割当（naive をフラグ）。
6. **バグなら真因の実測確定計画**: 適切な E2E タイプで真因を実測/再現してから直す（コード読解の仮説を確定扱いしない）。
7. **①証拠ゲート仕様を埋め込む**: 該当 realgui を scoped 実行＋証拠添付を必須チェックボックス化（実行は `/gui-verify`）。

**ゾーン境界を動かす変更**（frame 幅/grip 寸法/軸幅 等）には「既存 realgui の全掴み点を境界マージンで再監査せよ」を必ず出す（掴み点の move/QDrag ゾーン誤侵入は assert 失敗でなくハング）。

**グローバル介入を導入/変更する変更**（`QApplication`/共有祖先への `installEventFilter`・グローバルショートカット・app 全体のイベント/フォーカス監視 等「X のとき Y する」インターセプタ）の E2E 受け入れは**両方向＋実組立てが必須構成要素**:
- **発火側**: 意図した条件で介入が働く（realgui 実 OS 入力）。
- **非発火側**: 介入対象 subtree 内の**既存操作が引き続き完遂する**こと（例: 軸クリック活性化→続くジェスチャが最後まで成立）を**実 OS 入力**で検証。合成 `notify(target, ev)` は1配送のみで、実クリックが生む配送列（QWindow→target→未 accept 時の祖先バブル）を再現しない＝非発火側の証明には使えない。
- **ハーネス**: 介入コンポーネントと**その祖先チェーン**が実在する実アプリ組立て（`MainWindow`）。bare 部分組立て（介入未設置）や中間コンテナの top-level 化（祖先なし＝バブル消失）は構造的 false-green（FU-15 退行の真因・`reference/e2e-model.md` の落とし穴参照）。

## ノイジーな調査の委譲（任意）
似た既存入力経路テストの走査・再利用パターン抽出は `gui-test-strategist` サブエージェントに dispatch し**結論だけ**受け取る（計画コンテキストを汚さない）。

## 出力
`reference/output-template.md` に従いタスクごとの分析ブロックを返す。非 GUI・可視挙動不変のタスクは「Layer A のみ・E2E 不要・標準 Red/Green」と返す。
