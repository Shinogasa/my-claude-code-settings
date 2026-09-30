---
adr: 21
date: 2026-09-30
status: accepted
---

# learning-mode を常時ruleと詳細skillに分ける

## 背景

`rules/learning-mode.md` は `paths:` を持たない常時ruleで、12,334文字・474行ある。
`/context` の実測で 11.4k tokens を占め、Memory files 22.7k tokens の約半分にあたる。
毎リクエストで送られるため、ツール呼び出しの多いsessionほど固定費が積み上がる。

節ごとに見ると、常時必要なのは発火の判定と両学習モードの共通方針（約4割）で、
問いの出し方・★ Delta の書式・補足欄の供給規則・合理化防止・記録手順（約6割）は
発火が決まってから読めば足りる。

`code-learning` は ADR 0012 で「常時ruleは入口、手順はskill」の二層構成を採り、
両ホストでの発火を実測済みである。

公式仕様では、`paths:` の無いruleはcompact後にディスクから再注入される。
呼び出したskill本文は1件5,000 tokens・合計25,000 tokensまで先頭から再注入される。
Codexはskillの名前とdescriptionだけを先に見て、選んだときに本文を読む。
Codexでcompact後にskill本文がどう扱われるかは公式資料に記載が無い。

## 決定

- 常時ruleには、基本方針の要約、コード学習との境界、両学習モードの共通方針（無改変）、
  設計Predictの発火判定、開示前の禁止事項、詳細skillへの入口だけを残す
- 問いの出し方、理由フェーズ、★ Delta の書式と3軸評価、記録手順は
  `skills/learning-mode/SKILL.md` へ移す
- 概念名・定石・次の問いの供給規則と合理化防止の表は `skills/learning-mode/references/` へ移す
- ruleの入口に、発火時は問いを出す前にskillを全文読むこと、継続中のイベントで
  compactやresumeが入ったらskillを再読することを置く
- 共通方針の正本は常時ruleの1箇所に保ち、skillとreferencesへ複製しない
- ruleの目標は6,000文字以下、skillは5,000 tokens以内・500行未満とする

## 検討した代替案

### A. 全部をskillへ移し、ruleは入口だけにする

最も軽い。しかし発火の判定そのものが常時コンテキストから消え、skillのdescriptionだけで
判断点を拾うことになる。判定の精度が下がると学習モードが黙って止まり、止まったことに気づけない。
Codexでのcompact後のskill挙動も未確認であるため採らない。

### B. `paths:` を付けて、対象ファイルを読んだときだけ読み込む

判断点はファイル種別に閉じない（設計・原因分析・レビューはどのファイルでも起きる）。
公式仕様では `paths:` 付きruleはcompact後に戻らない。常に効く必要がある規約に付けないという
既存方針（CLAUDE.md）にも反するため採らない。

### C. 判定と ★ Delta の書式を常時ruleに残し、記録と合理化防止だけをskillへ移す

発火後の書式崩れには強い。しかし削減量が小さく（★ Delta 関連だけで約4,000文字残る）、
書式は発火時にskillを読めば足りるため採らない。

### D. 現状維持

変更リスクは無い。しかし固定費が続き、公式の推奨（手順はskillへ、CLAUDE.md相当は短く）から
外れたままになるため採らない。効果測定の結果によって学習モード自体を止める判断は、別に行う。

## 結果

実装後のサイズは、常時ruleが **4,340文字・154行**、skill本文が **5,232文字・219行**。
旧ruleの12,334文字から、常時読み込む文字数を7,994文字減らした。
`/context` での実ホスト測定は未実施であり、token数の削減量は未確認。

旧ruleの空行区切り99段落について、新rule・skill・2つのreferencesへ全文一致で照合した。
90段落は一致し、残り9段落は以下の意図的な変更だった。相互参照を置換した3段落も、置換後の全文一致を確認した。

| 旧ruleの段落 | 扱い |
|---|---|
| `基本方針` の5段落 | 設計書3.1どおり4文へ要約 |
| `L1 を捨てるわけではない` の1段落 | 設計書3.1どおり `定石` の参照文へ短縮 |
| ★ Delta書式とreferences内の3段落 | 移動先に合わせた相互参照の修正 |

削った例示はなし。先頭40文字での補助照合では99段落中93段落が一致し、残る6段落は上記の要約に該当する。

最終検査では全538テストが通過し、`bash -n setup.sh` と `git diff --check` も成功した。
共通方針の節は旧ruleとバイト単位で一致している。

良くなること:

- 常時コンテキストが約半分になる見込み（11.4k → 6k tokens 前後。実装後に実測して追記する）
- 判定は常時ruleに残るため、compact後も必ず効く
- code-learningと同じ構成になり、両モードの読み込み方が揃う

諦めること・既知のリスク:

- 発火時にskillを読む1手が増える。読み忘れると書式が崩れる
- skill本文がcompactで切り詰められる可能性がある。重要事項を先頭に置いて緩和する
- Codexでのcompact後のskill再注入は未確認のまま。ruleの「再読」指示で補う
- 当初見込みの3,000文字には届かない。共通方針と判定の文言を削らないことを優先した

## 根拠

- https://code.claude.com/docs/en/context-window （What survives compaction）
- https://code.claude.com/docs/en/skills （supporting files、500行、description 1,536文字、compact後の再注入）
- https://code.claude.com/docs/en/memory （CLAUDE.mdとskillの使い分け、paths付きrule）
- https://learn.chatgpt.com/docs/build-skills （Codexのskill段階的開示）
- https://learn.chatgpt.com/docs/agent-configuration/agents-md （project_doc_max_bytes 32 KiB）
- `docs/adr/0001-learning-mode-prediction-format.md`、`docs/adr/0007-learning-mode-decision-layer-gate.md`、
  `docs/adr/0012-code-learning-mode.md`、`docs/adr/0017-programming-learning-integration.md`
- `docs/superpowers/specs/2026-09-30-learning-mode-rule-skill-split-design.md`
