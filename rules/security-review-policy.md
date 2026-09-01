# セキュリティレビュー方針

## security boundary

変更が次の境界に一致するかを、完了前に毎回分類する。

- authentication（認証）
- authorization（認可）
- user input（ユーザー入力）
- API endpoints
- file uploads
- secrets
- payments
- raw SQL
- cryptography
- external integrations
- permissions
- deployment settings

## 意味レビューの発火条件

上記の security boundary に一致する変更だけ、完了前に `security-reviewer` による
意味レビューを必須とする。ordinary changes では自動LLM security reviewを起動してはいけない。

`security-reviewer` は軽量モデルによる意味レビューであり、静的解析、テスト、secret scan、
依存関係監査などの決定的検査を置き換えない。決定的検査は変更内容に応じて別途実行する。

`security-reviewer` が Critical findings または `Confidence: insufficient` を報告した場合は、
結果を人間へ提示して確認を得る。強いモデルを使う追加レビューは、人間の確認前に
自動でspawnしてはいけない。
