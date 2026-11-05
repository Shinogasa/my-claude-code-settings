---
adr: 49
date: 2026-11-06
status: accepted
---

# ECC（affaan-m/ECC）からは、新しい資産を導入しない

## 背景

解く問題: ECC には、Go や Kotlin のバックエンド開発と、エージェント設定の改善に役立つスキルが残っていないか。
残っていないなら、ECC を候補として何度も見直す手間をなくしたい。

`0ca0337`（2026-04-07）で、[affaan-m/ECC](https://github.com/affaan-m/ECC)（旧 everything-claude-code）からスキル・エージェント・コマンド・ルールを写して導入した。
写したときのcommitは記録しておらず、上流との差分を追えない。2026-10-07 には、直近60日の会話記録206件で利用が0件だった
commands 10件・skills 7件を削除している（`7d7ebf5`）。

2026-11-05、mattpocock/skills の `grill-me` を公式submoduleへのsymlinkに置き換えた（PR #131、ADR 0035と同じ方式）。
その流れで、ECCにも導入する価値のあるスキルが残っていないかを調べた。

ECCの規模（2026-11-05時点のmain）は、ファイル6,449・スキル314・エージェント71・コマンド98・ルール23言語分。
スキルの大半は医療、物流、金融、動画制作、homelab などの分野向けである。

ユーザーの作業（Go と Kotlin のバックエンド、エージェント設定の改善）に関わる18個を読み、業務のリポジトリと照らし合わせた。

| スキル | 分かったこと |
|---|---|
| `golang-patterns`・`golang-testing` | Go 1.18〜1.20 前提で止まっている。`slog`、`errors.Join`、`t.Context()`、`b.Loop()`、`testing/synctest` が無い。業務の Go リポジトリは Go 1.27 で、`t.Context()` を491ファイル、`cockroachdb/errors` を775ファイル、testify を693ファイル、go.uber.org/mock を620ファイルで使っている。スキルは、どのライブラリにも触れていない |
| `kotlin-testing` | Kotest 6.1.4 前提で、`FunSpec` が中心。業務の Kotlin サービスは Kotest 5.9.1 で、テストはすべて `DescribeSpec`（36ファイル） |
| `kotlin-ktor-patterns` | Ktor 3.4.0 前提で、Routing DSL、Authentication、StatusPages を手で書く。業務のサービスは Ktor 2.3.12 で、ルーティングは OpenAPI からの生成。どちらのプラグインも使っていない |
| `kotlin-patterns` | エラー処理は `Result` と例外。業務のサービスの標準は Arrow の `Either`（211ファイル）で、スキルは Arrow に触れていない |
| `error-handling` | Go の節は約45行。コード例は `QueryRow` から `(user, err)` を受け取っていて、そのままではコンパイルが通らない |
| `api-design`・`database-migrations`・`deployment-patterns` | 2026-10-07 に、利用0件で削除したもの |
| `skill-stocktake` | 結果を `~/.claude/skills/skill-stocktake/results.json` へ書く。symlinkで配ると、submoduleの中を汚す |
| `config-gc` | `~/.claude` のリンクの名前を変えたり移動したりする。`setup.sh` が張ったリンクの管理とぶつかる |
| `security-scan` | 実体は外部の npm パッケージ `ecc-agentshield` を `npx` で実行するだけ |

言語のスキルは、その言語のエキスパートが手入れしている一次資料に見えなかった。
「AIが生成した」とまでは確かめていない。根拠は、上の古さ、誤り、分野の広さである。

## 決定

2026-11-06、ユーザーが会話の中で決めた。決めたのは ECC についてだけで、ほかの外部スキル集の扱いは決めていない。

- ECCからは、スキル・エージェント・コマンド・ルールを新しく導入しない
- 言語やフレームワークのベストプラクティスが必要なら、公式の一次資料から取り込む（backlog「各言語の公式資料から、ベストプラクティスを導入する」）
- 導入済みのECC由来の資産（`skills/backend-patterns` など）をどうするかは、別に決める（backlog「ECC由来の資産を、上流submoduleへのsymlinkに置き換えるか決める」）
- 見直す条件は置かない。ECC のスキルは頻繁には更新されず、更新されても、それで効果が出るかは別だから

決め手は、言語スキルがその言語のエキスパートの手入れしたものに見えなかったことである。
`kotlin-testing` はモック（MockK）とプロパティテストが業務のサービスと合っていて、一度は候補に残った。
しかし同じ理由で、ほかの言語スキルと一緒に見送った。

## 検討した代替案

### A. ECCをsubmoduleにして、合うスキルだけを配る（ADR 0035 と同じ方式）

上流を追える点は良い。しかし、配る価値があると判断できたスキルが無かった。最後まで候補に残った `kotlin-testing` も、
業務のサービスのバージョン（Kotest 5 と 6）とテストの書き方（`DescribeSpec` と `FunSpec`）が合わない。
仮に1つ配るとしても、そのために6,449ファイルを抱えると、cloneと `submodule update` が重くなる。採らない。

### B. 合うスキルだけをコピーし、写した上流のcommitを記録する

submoduleより軽い。しかし、写す価値のあるスキルが無かった。内容の古さと誤りは、コピーしても直らない。採らない。

### C. Claude Code のプラグインとして入れる

ECCはプラグインとしても配られているが、全資産が一括で入る。superpowers や `code-review` と役割が重なり、
過去に、組み込みの `/verify` などを同名で上書きした問題（`7d7ebf5`）も起きている。採らない。

### D. 言語スキルを入れ、プロジェクトの CLAUDE.md で差分を打ち消す

例えば、業務の Kotlin サービスの CLAUDE.md に「テストは `DescribeSpec`」と書く。打ち消す行は数行で済む。
しかし、打ち消しが必要な時点で、スキルがプロジェクトの規約と競合している。グローバルのスキルとプロジェクトの文書が
違うことを言うと、AIがどちらに従うかは保証されない。Go では方針の違いが大きく（エラー、テスト、ログのライブラリ）、
数行では打ち消せない。採らない。

## 結果

- 良くなること: 古い書き方や誤ったコード例が、AIの出力やユーザーの学習に入らない。Go は重点学習中なので、特に効く
- 諦めること: ECCが新しく足すスキルを、まとめて追う手段は持たない
- 既知のリスク: 調べたのは314個のうち18個だけ。残りの296個は、description と名前から「分野が違う」と判断しただけで、
  「古くても雛形として使える」といった使う側の見方では確かめていない。集めた材料は、導入しない方向のものに偏っている。
  関係のある分野のスキルが新しく足されても、この ADR があるかぎり気づけない

## 根拠

- ECCのファイル一覧とスキル本文: `gh api repos/affaan-m/ECC/git/trees/main?recursive=1` と各 `skills/<名前>/SKILL.md`（2026-11-05取得）
- 業務のリポジトリ: `go.mod`、`gradle/libs.versions.toml`、ソースの grep による件数（2026-11-05計測）
- 削除の経緯: `7d7ebf5`（2026-10-07）
- 配布方式: ADR 0035、PR #131
