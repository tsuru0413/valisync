---
name: gui-verify
description: Use when a PySide6/pyqtgraph GUI change is nearing done — before declaring a user-facing feature complete, before merge, or whenever headless/CI is green but no one has driven the real app at real scale.
---

# gui-verify — 十分な E2E 検証で先回りする merge 前ゲート（課題①）

FU-01〜17 は全て「headless は緑だが、実アプリを実スケールで操作していないので、ユーザーが触って初めて課題が出た」＝手戻り。本ゲートは **merge/done 宣言の前に Claude が先回りで十分な E2E を実行**し、ユーザーより先に課題を捕まえる。

**REQUIRED BACKGROUND:**
- `reference/proactive-e2e.md`（先回り E2E の HOW: ジャーニー駆動・prod スケール実測・スクショ観測）。
- `reference/gate-and-pitfalls.md`（①証拠ゲート手順・E2E スペクトル/入力の出所・実行関連 false-green 落とし穴）。
- `reference/realgui-recipe.md`（realgui 駆動プリミティブ）。

## merge 前ゲート = 以下がすべて揃ったとき充足

- **(a) headless full**: `uv run pytest` が **0 errors**（realgui 全 pass でもテスト間汚染で CI は赤・memory `gui_qtbot_addwidget_vs_manual_delete_cascade`）。
- **(b) E2E 十分性 contract**: 変更が触れるジャーニーの**各ユーザー可視効果**に、正しい E2E タイプの**実 observable** が対応する ——
  1. **ジャーニー同定**: 変更を diff でなくユーザー操作（開く→ブラウズ→フィルタ→プロット→解析→閉じる）の視点で捉える。
  2. **効果ごとの実 observable**: 入力経路=**realgui スクショ**／perf=**prod スケール実測**（値 vs 目標）／描画=**スクショ目視**。
  3. **prod スケール**: perf/描画がスケールしうるなら `demo_data/prod_demo.mf4`（330k ch）で実測（小データは FU-11/12/16 を隠す）。
  4. **実経路 exercise**: E2E 証拠が**変更した挙動そのもの**を実経路で通す（同名だが別コードを触るテストはカバレッジでない）。
  5. **非プロキシ**: observable がユーザーの見る終状態そのもの（`isVisible`/`setText`1回/小データ perf で代替しない）。
- **(c) ①realgui 証拠**: 入力経路を変更したなら該当 realgui を scoped 実行＋証拠添付（`reference/gate-and-pitfalls.md`）。
- **(d) CI 緑**（push 済みなら確認）。

## 判定の形（positive contract）

充足/未充足を、(b) の**必須構成要素（ジャーニー／実 observable／prod スケール／実経路 exercise／非プロキシ）に一致するか**で出す。**未充足なら、欠けている構成要素を具体的に名指し**し、それを埋める観測手順（`reference/proactive-e2e.md`）へ誘導する。非 Windows・ディスプレイ無しで (c) を実行できない場合は未充足（`skipped` を検証済みと数えない）。

### 充足と誤認しやすい不十分な E2E 証拠（どの要素が欠けるか）

- **同名だが別コードを触る realgui** → 実経路 exercise 欠（変更挙動を通していない）。
- **`isVisible()` 等の嘘プロキシ** → 実 observable 欠（画面外/タブ裏でも True・FU-04）。
- **小データでの perf 計測** → prod スケール欠（330k でのみ顕在化・FU-11）。
- **スクショ無しの視覚判定** → 描画 observable 欠（FU-12）。

## 手順

1. **変更経路を特定**: `git diff --name-only main...HEAD -- src/valisync/gui/`（未コミットは `git status --short -- src/valisync/gui/` 併用）。空なら「GUI 入力経路の変更なし → ①対象外」。ただし perf/描画変更は入力経路が無くても (b) を満たす。
2. **ジャーニーと効果を同定**（`reference/proactive-e2e.md`）: 触れる区間と各ユーザー可視効果を列挙。
3. **効果ごとに contract 照合**: 各効果に (b) の 5 要素が揃うかを確認。揃わない要素は名指しして埋める。
4. **先回り E2E を実行**:
   - realgui（入力経路変更時・該当のみ）: `tests/realgui/test_*.py` を全列挙し、変更ファイルのモジュール/ウィジェット/関数名を参照するものへ対応付け（`grep -l <識別子>`・固定表に頼らない・1変更が複数に対応し得る）→ `uv run pytest --realgui tests/realgui/test_X.py -v`。対応 realgui が無い経路はフラグ（黙って pass しない）。
   - perf/描画: `reference/proactive-e2e.md` に従い prod スケールで実測/スクショ。
   - headless full: `uv run pytest`（0 errors）。worktree なら先に `uv sync --extra dev`。
5. **証拠集約**: 実行した realgui 名・pass/fail・実測値 vs 目標・スクショパスをまとめる。
6. **ゲート判定**: (a)〜(d) を出力。未充足なら欠けた構成要素と埋める手順を示す。

## 出力フォーマット

- **headless full**: `uv run pytest` の結果（passed / errors 数）。
- **(b) contract 照合**: 効果ごとに E2E タイプ／実 observable／prod スケール要否／実経路 exercise の充足（欠けた要素は名指し）。
- 実行した realgui・perf 実測・スクショの証拠。
- **ゲート判定**: 充足 / 未充足（＋ (a)(b)(c)(d) の充足状況・未充足要素・埋める手順）。
