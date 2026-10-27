---
adr: 40
date: 2026-10-27
status: accepted
---

# 運用方針を公式の best-practices ページに合わせる

## 背景

submodule `claude-code-best-practice` が追っているのは仕様（キー名、frontmatter、hookイベント）までで、
公式の best-practices ページ（運用の考え方）とは比べていなかった。2026-10-27に全文を突き合わせたところ、
次の食い違いが見つかった。

- `CLAUDE.md` は、サブエージェントを「メインのコンテキストをきれいに保つため、積極的に使う」と書いていた。
  公式は、この使い方を「もうやめてよい助言」に挙げている
- `CLAUDE.md` 177行に、`paths:` の無いrule 11本・748行が加わって、毎セッション約925行が読み込まれていた。
  公式の目安はCLAUDE.mdで200行未満。さらに `CLAUDE.md` は9本のruleを「全文読め」と指示していた。
  Claude Codeでは、これらはすでに起動時に読み込まれている
- `CLAUDE.md` に太字の強調が多かった。公式は、強調を重ねるとルールを過剰に当てはめると述べている
- `settings.json.template` が `effortLevel: xhigh` を常時指定していた。公式の既定はmediumで、
  high以上は見落としやすいケースに使うものとしている
- 副作用のあるskillに `disable-model-invocation` が無く、`.worktreeinclude` も無かった

ユーザーの方針は「基本はベストプラクティスに沿わせる。公式リファレンスなので最大の効果が出るはず」。

## 決定

1. サブエージェントは、公式が挙げる用途（並列化、長い出力の隔離、独立レビュー、ツールを絞った作業）に使う
2. 必須読み込みはCodex CLIだけの手順にする。Claude Codeには読み直させない
3. `CLAUDE.md` の強調を減らす。リスト見出しの太字だけを残す
4. `effortLevel` をテンプレートから外し、既定に戻す
5. `pr-create` 系のskillとcommandに `disable-model-invocation: true` を付ける。Codex CLIは、このfrontmatterを
   読まない。そのため、公式の手段である `agents/openai.yaml` の `policy.allow_implicit_invocation: false` も置く
6. `.worktreeinclude` で `.env` と `.githooks/patterns-local.txt` をworktreeへコピーする
7. `paths:` は「そのruleが要る前に、必ず特定の種類のファイルに触れるか」で付けるかを決める。
   当てはまるのはコードを書くときの規約 `rules/ecc-coding-style.md` だけなので、これにだけ付ける

## 検討した代替案

### `paths:` を広く付ける

コンテキストは最も減る。しかし、学習モード・タスク管理・不在の主張・人格・出力形式は、
ファイルに触れない相談や計画の会話でも最初の応答から必要になる。`paths:` を付けると読み込まれないまま進み、
compactの後も一致するファイルを読むまで戻らない。公式の主張も「一部でしか要らないものだけ絞る」なので、
広く付けることは公式に沿っていない。ADR 0021のBを却下した理由もこれと同じ。

### `security-review-policy.md` と `code-learning.md` にも `paths:` を付ける

どちらもコード変更の中で効くので、付けることはできる。しかし、security boundary には
`.github/workflows` などの設定変更も入り、globが広くなる。code-learning は、compactの後に
次のコードを読むまで抜ける。押さえ損ねたときの損失が削減量より大きいので採らない。

### Stop hookで完了前のテストを強制する

公式は Stop hook による検査の強制を挙げている。しかし、このリポジトリでは
`require-full-tests-before-pr.py` がPR作成時に全テストを強制している。止まるたびに全テストを走らせるのは
時間がかかりすぎる、とユーザーが判断して、今のままにした。

### 今回sandboxを有効にする

全プロジェクトに効き、`gh`・`uvx`・ネットワークを使うコマンドが壊れうる。検証は別タスクに回した（backlog）。

### サブエージェントをhaikuにする

公式は、単純な作業をするサブエージェントにhaikuを勧めている。今ある10体はレビューや改修を担うもので、
単純な作業に当てはまるものが無いので変えない。

## 結果

- Claude Codeでは、毎セッションの読み込みから `ecc-coding-style.md` の93行が外れる。
  必須読み込みによる読み直しのツール呼び出しも無くなる
- effortがmediumに下がるので、難しい調査では自分で `/effort high` を指定する必要がある
- ReviewAndDesignスタイルの見直しと、sandboxの有効化は別タスクとしてbacklogに残した

## 根拠

- https://code.claude.com/docs/en/best-practices （2026-10-27取得）
- https://code.claude.com/docs/en/memory （2026-10-27取得。path-specific rules、ユーザーレベルruleのパス起点、compact後の挙動）
- ADR 0021（`paths:` を learning-mode に付けない判断）
