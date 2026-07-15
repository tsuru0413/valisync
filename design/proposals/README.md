# Proposals — 検討中のデザイン改善案カード

運用ループ (docs/design.md) の手順1で、改善案 A/B をここに HTML カードとして作成して
push し、claude.ai/design の Proposals グループで比較する。採用されたら tokens.py へ
反映し、このディレクトリと Claude Design 側の両方からカードを削除する。

カード規約: 1行目 `<!-- @dsCard group="Proposals" -->`・`<!-- @TOKENS_CSS -->` 注入
プレースホルダ・**提案で変える値のみ**生値で書き、他は `var(--vs-*)` を参照する
(現行との差分が読み取れるように)。
