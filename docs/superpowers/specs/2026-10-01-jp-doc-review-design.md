# 日本語文書のレビューとスキル読み込み確認の設計

## 目的

Claude Codeが日本語のMarkdown・設定ファイルを書いたとき、またはConfluenceへ投稿するときに、
yomiyasuの基準で文章をレビューし、自然な日本語に直す。

普段のセッションで消費するコンテキストは増やさない。yomiyasu本体（SKILL.mdとreferenceで約40KB）を読むのは、
レビュー用のサブエージェントだけにする。サブエージェントは、メインのエージェントに結果の要約だけを返す。

あわせて、スキルの読み漏れを会話記録から機械的に見つける（5節）。読み漏れとは、スキルを呼んだのに、
そのスキルが読むよう求める資料を読まないまま作業を進めることを指す。

判断の経緯と却下した案は `docs/adr/0024-jp-doc-review-hook.md` に記録する。

## 範囲

| 項目 | 内容 |
|---|---|
| 対象ホスト | Claude Codeのみ。Codex対応はbacklogに積む |
| 対象リポジトリ | すべて（グローバル設定の `settings.json` に配線する） |
| 対象ファイル | 日本語を含む `.md`・`.toml`・`.yaml`・`.yml`・`.json` |
| 対象の投稿 | Confluenceのページ作成・更新、フッターコメント、インラインコメント |
| 読み込み確認の対象 | 対応表に登録したスキル。最初はyomiyasuだけを登録する |

次のものは対象外とする。

- Bash経由の書き込み（`cat > file` やスクリプトによる書き込み）。Write・Edit・NotebookEditを通らないため、記録できない
- submoduleの中のファイル、`node_modules`、`vendor`、`dist`、`build`、ロックファイル
- レビュー用の下書き置き場（`~/.claude/state/jp-doc-review/drafts/`）

## 全体の流れ

```
[書き込み]  Write / Edit / NotebookEdit
     │  PostToolUse: 対象ファイルなら、パスと書き足した日本語の文字数を記録する（出力なし）
     │  レビュワー（agent_type = jp-doc-reviewer）の書き込みは記録しない
     ▼
[作業の終わり]  Stop
     │  記録から、まだ存在し、かなを含み、書き足した日本語が100文字以上のファイルを集める
     │  該当があればblockし、jp-doc-reviewerへのレビュー依頼を返す
     ▼
[レビュー]  サブエージェント jp-doc-reviewer（model: opus）
     │  yomiyasuを全部読み、意味を保ってファイルを書き直し、リンターで確かめる
     │  メインには「変えた点」と「書き手に確かめたい点」だけを返す
     ▼
[メイン]  結果をユーザーに伝えて終わる（2回目のStopは止めずに通す）

[Confluence]  create/updateConfluence*
     └ PreToolUse: 日本語が100文字以上なら、1回目だけ止めて下書きのレビューを求める
```

## 構成要素

| 追加・変更するもの | 役割 |
|---|---|
| `skills/yomiyasu`（submodule） | commitを固定したyomiyasu本体。`manifests/skills.json` の `shared` に追加し、既存の仕組みで両ホストにリンクする |
| `hooks/jp-doc-review.py` | 1本のスクリプトで、記録・集約・Confluenceの事前チェックを担う。第1引数でイベントを切り替える |
| `agents/jp-doc-reviewer.md` | レビュー用サブエージェント。Codex用の定義も既存の生成スクリプトで作られるが、Codexには起動するフックが無い |
| `hooks/skill-read-check.py` | スキルごとの必読資料を会話記録と照合する、汎用の確認。StopとSubagentStopで動く |
| `manifests/skill-required-reads.json` | スキル名と必読資料の対応表 |
| `settings.json.template` | 5つのフック（PostToolUse、PreToolUse、Stop 2本、SubagentStop）を配線する |

常時読み込みのruleは追加しない。

## 定数

| 名前 | 値 | 意味 |
|---|---|---|
| `MIN_JP_CHARS` | 100 | レビューを起動する下限。書き足した日本語の文字数で数える。記録・集約・Confluenceで共通 |
| `TARGET_SUFFIXES` | `.md` `.toml` `.yaml` `.yml` `.json` | 記録の対象にする拡張子 |
| `STATE_RETENTION_DAYS` | 7 | 状態ファイルを残す日数。これを過ぎたものはStopのたびに消す |
| `REVIEWER_AGENT` | `jp-doc-reviewer` | レビュワーのagent名。記録から除外する判定にも使う |

日本語の文字数は、ひらがな・カタカナ・漢字の数で数える。ただし、かなを1文字も含まない文字列は0とみなす。
漢字だけの文字列は、中国語と区別できないからである。

## 1. 記録（PostToolUse）

matcherは `Write|Edit|NotebookEdit` とする。

1. 入力の `agent_type` が `jp-doc-reviewer` なら何もしない
2. 書き込み先のパスを取る（Write・Editは `file_path`、NotebookEditは `notebook_path`）
3. 拡張子が `TARGET_SUFFIXES` に無い、または対象外のパスなら何もしない
4. 書き込んだ文字列（Writeは `content`、Editは `new_string`、NotebookEditは `new_source`）の日本語の文字数を数える
5. `~/.claude/state/jp-doc-review/<session_id>.jsonl` に `{path, jp_chars}` を1行追記する

標準出力には何も出さない。だから、この段階ではコンテキストを消費しない。

submoduleの判定は次のとおり。ファイルのあるディレクトリから親へたどる途中で、`.git` ディレクトリより先に
`.git` ファイルが見つかれば、submoduleの中とみなす（submoduleの作業ツリーには `.git` ファイルが置かれる）。

入力のフィールド名は一次資料と実機の入力で確かめてから実装する。

## 2. 集約（Stop）

入力の `stop_hook_active` で、2回目のStopかどうかを見分ける。

**1回目（`stop_hook_active` が `false`）**

1. 記録を読み、パスごとに日本語の文字数を合計する
2. 次をすべて満たすパスを集める
   - ファイルがまだ存在する
   - 中身にかなを含む
   - 合計が `MIN_JP_CHARS` 以上
3. 該当が無ければ通す。記録は残し、次のターン以降の書き込みと合算する
4. yomiyasu（`~/.claude/skills/yomiyasu/SKILL.md`）が見つからなければblockしない。レビューを省略したことを、`systemMessage` でセッションに1回だけ表示する
5. 該当があれば、依頼したパスを `<session_id>.dispatched.json` に書き、`{"decision": "block", "reason": ...}` を返す

reasonには、対象のパスの一覧と、次の指示を書く。

- jp-doc-reviewerサブエージェントに、これらのパスを渡してレビューさせる
- レビュワーの報告を受けたら、変えた点と書き手に確かめたい点をユーザーに伝える

**2回目（`stop_hook_active` が `true`）**

依頼したパスを記録から消して、通す。メインのエージェントが依頼に従わなかった場合も、ここで止まれる。
1回だけ促し、それでも動かなければ通す作りである。

通す前に、メインの会話記録を確かめる。1回目のStopより後に、`subagent_type` が `jp-doc-reviewer` の
Agent呼び出しが無ければ、レビューが実行されなかったことを `systemMessage` で表示する。
メインのエージェントが自分で書き直したと報告しても、ユーザーはこの表示で気づける。

## 3. Confluenceの事前チェック（PreToolUse）

matcherは `mcp__.*__(create|update)Confluence(Page|FooterComment|InlineComment)` とする。
MCPサーバー名が変わっても捕まえられるように、サーバー名の部分は正規表現で受ける。

1. `body` と `title` に含まれる日本語が `MIN_JP_CHARS` 未満なら通す
2. 投稿先のキーを作る。ツール名と、`pageId`・`parentCommentId`・`title` のうち最初に見つかった値を組み合わせる
3. そのキーへの投稿がセッションで1回目なら、次のようにする
   - 本文を `~/.claude/state/jp-doc-review/drafts/` に書き出す。拡張子は `contentFormat` に合わせる（`markdown` は `.md`、`html` または指定なしは `.html`、`adf` は `.json`）
   - 本文のハッシュをキーと一緒に記録する
   - `permissionDecision: "deny"` で止め、reasonで次を指示する。下書きをjp-doc-reviewerに渡して文章だけを直させること。HTMLのタグや `data-*` 属性は変えさせないこと。直した下書きの内容で投稿し直すこと
4. 2回目なら通す。本文のハッシュが1回目と同じなら、レビューされないまま投稿されたことを `systemMessage` で表示する

1回目は止めるので、Confluenceには何も送られない。

## 4. レビュワー（agents/jp-doc-reviewer.md）

| 項目 | 値 |
|---|---|
| tools | Read, Edit, Bash（リンターの実行用） |
| model | opus |

手順は次のとおり。

1. yomiyasuのSKILL.mdと、そこから参照されるreference（構文変換原則、語彙カタログ、ドメイン別仕様）を全部読む
2. ファイルごとにドメイン（tech・business・essay）を判定し、意味の4点（主張・比重・言い切りの強さ・文の働き）を保って書き直す
3. 同梱のリンターで確かめる。リンターの指摘を消すためだけの言い換えはしない
4. メインには、ファイルごとに「変えた点」と「書き手に確かめたい点（最大2点）」だけを返す

次のものは変えない。

- エージェント向けの指示ファイル（CLAUDE.md、`rules/`、`skills/`、`agents/`、`output-styles/`）の★ブロック・表・太字・箇条書き
- コード、識別子、URL、パス、コマンド
- テストやgrepが参照している文言
- Confluence下書きのHTMLタグと属性

## 5. スキルの読み込み確認（汎用）

スキルを呼んだのに、そのスキルが読むよう求める資料を読まないまま作業を進める失敗を、会話記録で見つける。

この仕組みで確かめられるのは「読んだかどうか」だけである。「使うべき場面でスキルを呼んだか」と
「読んだ内容に従ったか」は確かめられない。前者は、1〜3節のようなスキルごとの発火条件で補う。
後者は仕組みにしない。

**対応表**（`manifests/skill-required-reads.json`）

スキルごとに、置き場と必読資料を登録する。

```json
{
  "schemaVersion": 1,
  "skills": {
    "yomiyasu": {
      "root": "~/.claude/skills/yomiyasu",
      "allOf": ["references/gemini-syntax.md", "references/slop-catalog.md"],
      "anyOf": [["references/domains/tech.md", "references/domains/business.md", "references/domains/essay.md"]]
    }
  }
}
```

`allOf` の資料はすべて読む必要がある。`anyOf` は、組ごとに少なくとも1つを読めば満たす。

対応表には、読み漏れが実際に起きたスキルだけを登録する。条件付きで読む資料
（「迷ったときに読む」など）は登録しない。登録しすぎると正しい作業まで止めてしまい、
フックごと外される恐れがある。

**確かめ方**（`hooks/skill-read-check.py`）

1. 会話記録を読む。Stopでは `transcript_path`、SubagentStopでは `agent_transcript_path` を使う。
   最後のcompactより後の部分だけを対象にする
2. その範囲で、登録されたスキルが呼ばれたかを調べる。Skillツールの呼び出しか、
   そのスキルの `SKILL.md` のReadがあれば、呼ばれたとみなす
3. 呼ばれたスキルごとに、必読資料のReadがあるかを調べる。パスはsymlinkを解決した実体で比べる
4. 足りない資料があり、`stop_hook_active` が `false` なら、blockして読んでいない資料の一覧を返す
5. `stop_hook_active` が `true` なら通し、資料が読まれないまま終わったことを `systemMessage` で表示する

compactの区切りが会話記録にどう残るかは、実機の会話記録で確かめてから実装する。
会話記録の形式はClaude Codeの内部仕様で、公開された契約ではない。読めなかったときは、
確認できなかったことを `systemMessage` で表示する。

## 6. 失敗時の扱い

検査できなかったことを、問題なしとして扱わない。必ず画面に表示する。

| 状況 | 振る舞い |
|---|---|
| スクリプト内で例外が起きた | 内容を標準エラーに出し、終了コード1で終える。作業は止めないが、フックのエラーとして画面に表示される |
| yomiyasuが見つからない | レビューを起動せず、`systemMessage` でセッションに1回だけ表示する |
| 状態ディレクトリに書き込めない | 例外と同じ扱いにする |
| 記録が壊れている（JSONとして読めない行がある） | その行を飛ばし、飛ばした件数を `systemMessage` で表示する |
| 会話記録を読めない（形式が変わった） | 確認できなかったことを `systemMessage` で表示し、止めない |
| 対応表の資料がディスクに無い（上流で名前が変わった） | 対応表が古いことを `systemMessage` で表示し、その資料の確認を飛ばす |

## 7. 導入と移行

**新しいPC**: `git clone --recurse-submodules` の後に `bash setup.sh` を実行するだけで使える。
setup.shには、submoduleを初期化する処理が既にある。

**npx版から移る既存のPC**: 先に `npx skills remove -g yomiyasu` で外してから、`bash setup.sh` を実行する。
npx版を残したままにすると、`npx skills update` がsubmoduleへのリンクを通して、submoduleの中身を上書きする恐れがある。
setup.shは既存のリンクを衝突として検出するので、確認してから置き換える。

## 8. テスト

**単体テスト**（`tests/test_jp_doc_review_hook.py`、TDDで書く）

合成した入力をスクリプトに渡し、次を確かめる。

- 記録: 対象拡張子・除外パス・submodule・レビュワーの除外・かなを含まない文字列
- 集約: 100文字の境界、ファイルの削除、2回目のStopで通すこと、yomiyasuが無いときの表示
- Confluence: 100文字の境界、1回目のdenyと下書きの作成、2回目の許可、本文が同じときの警告、投稿先のキーの作り方
- 失敗時: 例外での終了コード、壊れた記録行の扱い
- 読み込み確認: Skill呼び出しとSKILL.mdのReadのどちらでも起動とみなすこと、`allOf` と `anyOf` の判定、symlinkを解決したパスでの比較、compactより前のReadを数えないこと、2回目は通して表示すること、会話記録が読めないときの表示
- 集約の2回目: レビュワーが起動していないときの表示

状態ディレクトリは環境変数で差し替えられるようにし、テストでは一時ディレクトリを使う。

**配線のテスト**: `settings.json.template` の5つのフックのmatcherとコマンドを固定する。

**実機での確認**: 合成した入力でのテストが通っても、実機で動く証拠にはならない。
実際のClaude Codeのセッションで次を確かめ、結果を記録する。

1. 日本語のMarkdownを書いて作業を終えると、jp-doc-reviewerが起動する
2. レビュワーの書き込みが記録されない（`agent_type` が実際に入力に入っている）
3. 2回目のStopで止まらずに終わる
4. Confluenceへの1回目の投稿が止められ、下書きが作られる（止めるので何も送られない）
5. yomiyasuを呼んで、referenceを読まずに作業を終えようとすると止められる
6. compactの区切りが会話記録のどこに残るか

## 既知の制約

- Bash経由の書き込みはレビューされない
- レビュワー以外のサブエージェントが書いた文書が、メインのセッションの記録に入るかは実機で確かめる
- 2回目のStopの前にメインのエージェントが新しく書いたファイルは、記録が依頼したファイルと一緒には消えず、次のターンのレビュー対象に回る
- yomiyasuのリポジトリには同じスキルの複製（`skills/yomiyasu/`）が入っているため、スキル一覧に `yomiyasu:yomiyasu` が重複して出ることがある
- レビューのたびにopusのサブエージェントが動くので、日本語の文書を書く作業は時間とトークンが増える
- 読み込み確認で分かるのは、資料を読んだかどうかまでである。読んだ内容に従ったかは確かめられない
- レビュワーがリンターを実行したかは確かめない
