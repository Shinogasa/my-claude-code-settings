---
adr: 36
date: 2026-10-14
status: accepted
---

# 個人プロファイルのセッションから起動する `codex` を、環境変数で個人用に固定する

## 背景

解く問題: 個人用のセッションでの作業に、会社のアカウントと予算が使われないようにする。

1台のマシンで、会社用と個人用のプロファイルを使い分けている。
Claude Codeは素の `claude` が会社用で、`ccp` が個人用。Codexは素の `codex` が会社用で、`cxp` が個人用（ADR 0026）。

2026-10-14、`ccp` で起動したClaude Codeのセッションで、個人の作業の確認に `codex exec` を実行した。
子の `codex` は、`CODEX_HOME` が未設定のため既定の `~/.codex` を読み、会社用で動いた。エラーは出ていない。
少量なら問題にならないが、続けば会社の予算を私用に使うことになる。

子プロセスがどのプロファイルで動くかは、ツールによって決まり方が違う。

- `codex` は、環境変数 `CODEX_HOME` で設定と認証情報の場所を決める。`cxp` もこの変数を個人用へ向けているだけである
- `claude` は、`~/.claude/settings.json` の `env` で接続先を決める。設定ファイルの値は、親から引き継いだ環境変数より優先される。
  そのため、`claude-headless` が目印 `CLAUDE_PROFILE` を見て `--settings` を付け分けている

Claude Codeの設定ファイルの `env` に書いた値は、Bashの子プロセスまで届く。
`ccp` のセッションのBashで `CLAUDE_PROFILE=personal` が見えることで確認した（2026-10-14）。

## 決定

2026-10-14、ユーザーが会話の中で次の2つを決めた。

- 方針: 個人用のセッションから起動する子のエージェント（Claude CodeとCodex）は、ユーザーの指示が無い限り個人用で動かす。
  ユーザーの言葉は「個人のプロファイルではユーザーの指示がない限り個人のプロファイルでclaude codeとcodexを起動するようにしたい」
- 順番: AIが示した3つの縛り方（①個人のClaude Code → `codex`、②個人のClaude Code → `claude`、③個人のCodex → `claude`）を、
  ①から順に対応する。ユーザーの言葉は「1から順に対応しよう」

このADRは①を扱う。②と③は `tasks/backlog.md` で追い、対応したらこのADRに追記する。
それまでは、子の `claude` から会社用へ流れる経路が残る（「既知のリスク」）。

- `setup.sh` は、`settings.personal.json` の `env` に `CODEX_HOME=<HOME>/.codex-personal` を書く
- `settings.json` の `env` にも `CODEX_HOME=<HOME>/.codex` を書く。
  個人用の値が会社用のセッションに紛れ込んでも、この値で上書きされる（`CLAUDE_PROFILE` と同じ考え方）
- 設定ファイルの `env` は `~` を展開しない。`setup.sh` が端末ごとの絶対パスを書く。
  パスは、引き継いだ `CODEX_HOME` ではなく `HOME` から決める
- 会社用を使うよう指示されたときは、`CODEX_HOME=~/.codex codex ...` と明示して起動する
- `setup.sh` は、個人用の `CODEX_HOME` を `cxp` と同じ条件で検査し、引っかかったら警告する（無い、会社用と同じ実体、権限が700でない）。
  無いときと権限が違うときは、警告して値をそのまま書く。会社用と同じ実体のときは、存在しない番兵のパス
  （`<HOME>/.codex-personal.SAME-AS-COMPANY-HOME`）を書き、子の `codex` をエラーで止める（fail-closed）

端末で直接打つ `codex` やGUIアプリは、今と同じく会社用で動く。ADR 0026が素の `codex` を会社用のままにした理由
（シェル統合が読み込まれないときに、`cxp: command not found` で気づける）は、この変更の後も成り立つ。

## 却下した案

### A. フックで素の `codex` の起動を止め、`cxp` を使うよう案内する

コマンドの文字列で判定するので、スクリプトの中からの起動、フルパスでの起動、`sh -c` で包んだ起動を見逃す。
環境変数なら、起動の書き方に関係なく子へ引き継がれる。

### B. 規約（rules）に「個人のセッションでは `cxp` を使う」と書く

守られたかどうかが成果物に残らない。今回の事故も、手順の中で `codex exec` と書いたまま実行して起きた。

### C. 素の `codex` を個人用にする

ADR 0026の案Cと同じ理由で採らない。素の `codex` が個人用で動くようになり、会社の作業が個人アカウントへ流れる経路ができる。

## 結果

- 個人用のClaude Codeのセッションから素の `codex` を起動しても、個人用で動く
- `~/.codex-personal` が無い端末やログインしていない端末では、`codex` はエラーで止まる。
  エラーを出さずに会社用へ切り替わることは無い。2026-10-14に確かめた（codex-cli、macOS）。
  - フォルダが無いとき: `Error finding codex home: CODEX_HOME points to "...", but that path does not exist`、exit 1
  - 空のフォルダのとき: `api.openai.com` が `401 Unauthorized` を返し、exit 1

### 諦めたこと

- `cxp` は起動のたびに検査するが、この経路では `setup.sh` を実行したときにしか検査しない。
  設定を作った後で `~/.codex-personal` を差し替えたり、権限を変えたりしても気づけない
  - 検査を `setup.sh` に置いたのは、子の `codex` の起動に割り込める場所が無いからである。環境変数を渡すだけなので、起動前に処理を挟めない
  - 検査に引っかかったときに値を書かない案も考えたが、採らなかった。値が欠けると、子の `codex` がエラーを出さずに会社用で動き、今回の事故に戻る。
    値を書いておけば、無いときは `codex` がエラーで止まる
  - 会社用と同じ実体のときに警告だけで値を書く案も、採らなかった。子の `codex` が会社の認証で動き、警告は `setup.sh` の出力に埋もれる。
    セキュリティレビュー（2026-10-14、Medium）の指摘を受けて、番兵を書く形に改めた
  - `setup.sh` を実行した後に `~/.codex-personal` を差し替えた場合は、この検査では見つけられない。起動のたびの検査は、②で足すフックで行う

### 既知のリスク

- `setup.sh` を実行するまで効かない。実行忘れを検出する仕組みが無いことはADR 0031で受け入れた制約で、この保護にもそのまま当てはめる。
  ②で足すフックに、`CLAUDE_PROFILE=personal` なのに `CODEX_HOME` が無いときに警告する検査を入れ、実行忘れに気づけるようにする
- 設定ファイルを手で書き換えた場合や、`--settings` に別のファイルを渡した場合は、この保護が外れる
- ②と③に対応するまでは、子の `claude` が会社用で動く経路が残る。子が `settings.json` を読み直すので、環境変数では固定できない。
  `tasks/backlog.md` の「個人用のセッションから起動する素の `claude` を止める」で追う

## 根拠

- ADR 0026（Codexの個人用に `CODEX_HOME` を分ける）
- `bin/claude-headless` の冒頭（設定ファイルの `env` が子へ届くことと、目印を両方のプロファイルに置く理由）
- `tests/test_setup_cli.py` の `test_profiles_pin_codex_home_for_child_codex` と `test_warns_when_personal_codex_home_*`
