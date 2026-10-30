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

`security-reviewer` は `gpt-6-sol` + `high` による意味レビューであり、
静的解析、テスト、secret scan、
依存関係監査などの決定的検査を置き換えない。決定的検査は変更内容に応じて別途実行する。

`security-reviewer` が Critical findings または `Confidence: insufficient` を報告した場合は、
結果を人間へ提示して確認を得る。Astraなど上位モデルを使う追加レビューは、人間の確認前に
自動でspawnしてはいけない。

## 指摘の仕分け

セキュリティレビューの指摘（コミットごとの自動LLMレビュー、`security-reviewer`、ブランチ全体のレビュー）は、
レビュワーが付けた重さ（High など）では仕分けない。次の2つを両方満たすものだけを「大きい問題」として、その場で直す。

1. 普段の作業で起きる形である。再現する入力が、わざと組んだ形ではなく、AIや利用者がふだん書く形になっている
2. 起きたら取り返しがつかない。secret が出力される、データが消える、作業が止まって回避できない

満たさないものは直さず、backlog に積む。直した修正が新しく開けた穴も、同じ2条件で仕分ける。
1の判定に迷ったら大きい側に倒して直し、報告に「迷った」と書き添える。

報告では、大きい問題と判定した指摘があるときだけ、2条件に当たる理由と一緒に表で示す。
無いときは「見送り N 件（backlog に積んだ）」の1行にする。利用者は判定を覆せる。
backlog に積んだ指摘は、利用者が定期的に棚卸しする。設計で脅威モデル（守る範囲）を決めたタスクでは、その範囲の外の指摘は1を満たさないものとして扱う。
経緯は ADR 0044 を参照。
