---
adr: 40
date: 2026-10-27
status: accepted
---

# 運用方針を公式の best-practices ページに合わせる

## 背景

目的は、公式の best-practices を見直し、コーディングエージェントの性能を最大限に引き出せるよう設定を調整し直すこと。

submodule `claude-code-best-practice` が追っているのは仕様（キー名、frontmatter、hookイベント）までで、
公式の best-practices ページ（運用の考え方）とは比べていなかった。2026-10-27に全文を読み比べたところ、
次の食い違いが見つかった。

- `CLAUDE.md` は、サブエージェントを「メインのコンテキストをきれいに保つため、積極的に使う」と書いていた。
  公式は、この使い方を「もうやめてよい助言」に挙げている
- `CLAUDE.md` の177行に、`paths:` の無いrule 11本・748行が加わって、毎セッション約925行が読み込まれていた。
  公式の目安はCLAUDE.mdで200行未満。さらに `CLAUDE.md` は9本のruleを「全文読め」と指示していた。
  Claude Codeでは、これらはすでに起動時に読み込まれている
- `CLAUDE.md` に太字の強調が多かった。公式は、強調を重ねるとルールを過剰に当てはめると述べている
- `settings.json.template` が `effortLevel: xhigh` を常時指定していた。公式の既定はmediumで、
  high以上は見落としやすいケースに使うものとしている
- 副作用のあるskillに `disable-model-invocation` が無く、`.worktreeinclude` も無かった

ユーザーの方針は「基本はベストプラクティスに沿わせる。公式リファレンスなので最大の効果が出るはず」。

## 決定

1〜6は、ユーザーの方針（公式に沿わせる）をAIが当てはめて決め、ユーザーが一覧で確認した。
7と、検討した代替案のうち Stop hook・sandbox は、ユーザーが個別に選んだ。

1. サブエージェントは、公式が挙げる用途（並列化、長い出力の隔離、独立レビュー、ツールを絞った作業）に使う
2. 必須読み込みはCodex CLIだけの手順にする。Claude Codeには読み直させない
3. `CLAUDE.md` の強調を減らす。リスト見出しの太字だけを残す
4. `effortLevel` をテンプレートから外し、既定（Opus 5.5ではmedium）に戻す。公式は、mediumで始めて足りなければ上げる
   という使い方を示しており、ユーザーもこれを採った。xhighを常時使うと、日常の作業にも時間とトークンを払い続ける
5. `pr-create` 系のskillとcommandに `disable-model-invocation: true` を付ける。Codex CLIは、このfrontmatterを
   読まない。そのため、公式の手段である `agents/openai.yaml` の `policy.allow_implicit_invocation: false` も置く
   （この決定はADR 0043で取り消した。ほかの決定は有効）
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

### サブエージェントの行を消し、既定の判断に任せる

公式は、Claudeが既定でExploreやforkへ自動的に任せるので、使えと頼む必要はめったに無いとしている。
「頼まなくてもやることは書かない」を厳しく当てはめれば、行ごと消すことになる。
ただし、公式はサブエージェントを使うなとは言っていない。やめてよいとしているのは、コンテキストを守るため、
またはより良い答えを得るために任せることだけである。元の方針「コンテキストをきれいに保つため、積極的に使う」は、
コンテキストが小さかった頃の前提に立っていて、1Mトークンのコンテキストウィンドウでは成り立たない。そこで「積極的に」を外し、
使う場面とコストを残す形にした。行ごと消すかはユーザーが比べて、残す方を選んだ。

### Stop hookで完了前のテストを強制する

公式は Stop hook による検査の強制を挙げている。しかし、このリポジトリでは
`require-full-tests-before-pr.py` がPR作成時に全テストを強制している。止まるたびに全テストを走らせるのは
時間がかかりすぎる、とユーザーが判断して、今のままにした。

### 今回sandboxを有効にする

全プロジェクトに効き、`gh`・`uvx`・ネットワークを使うコマンドが動かなくなりうる。検証は別タスクに回した（backlog）。

### サブエージェントをhaikuにする

公式は、単純な作業をするサブエージェントにhaikuを勧めている。今ある10体はレビューや改修を担うもので、
単純な作業に当てはまるものが無いので変えない。

## 結果

- Claude Codeでは、毎セッションの読み込みから `ecc-coding-style.md` の93行が外れる。
  必須読み込みによる読み直しのツール呼び出しも無くなる
- effortがmediumに下がるので、難しい調査では `/effort high` か、そのターンだけ `ultrathink` を指定する必要がある。
  公式の model-config ページ（先頭10万字。残り約2.8万字は未読）には、モデルが自分でセッションのeffortを変える手段の記載は無い。
  手間を減らす手段として、skillとサブエージェントのfrontmatterに `effort` を書けば、それが動く間だけeffortを上げられる。
  どこに付けるかは別に判断する
- ReviewAndDesignスタイルの見直しと、sandboxの有効化は別タスクとしてbacklogに残した

## 根拠

- https://code.claude.com/docs/en/best-practices （2026-10-27取得）
- https://code.claude.com/docs/en/memory （2026-10-27取得。path-specific rules、ユーザーレベルruleのパス起点、compact後の挙動）
- https://code.claude.com/docs/en/model-config （2026-10-27取得。effortの解決順、frontmatterの `effort`、`ultrathink`）
- ADR 0021（`paths:` を learning-mode に付けない判断）
