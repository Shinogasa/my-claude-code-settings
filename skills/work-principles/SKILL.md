---
name: work-principles
description: Use when the user asks how to approach their work — planning, writing proposals or specs, presenting, giving or receiving review, collaborating, or managing their own pace — and would benefit from a concrete working principle. Not for code-level or technology-selection questions.
---

# 仕事の原則で助言する

確認済みの仕事の原則集（`principles.json`、このスキルと同じディレクトリ）を引いて助言する。
原則集は生成物で、正本は非公開リポジトリにある。ここで書き換えない。

## 手順

1. 相談の場面を、`scenes`（計画、設計・企画、伝達、レビュー・評価、協働、自己管理）から1〜2個選ぶ
2. `principles.json` を読み、その場面を含み、`checkpoints` に `advice` を含む原則を選ぶ
3. 相談の状況が `not_applicable` に当たる原則は外す
4. 当てはまる原則を最大3件、原則IDと出典URL（`source_url`）を添えて示し、相談の状況に当てはめて助言する
5. 一見反対のことを言う原則を同時に引くときは、`themes` の `note`（使い分け）に従って、どちらがこの状況に当たるかを示す
6. 当てはまる原則が無ければ、無理に引かずにそう伝える

## 読み替えの規則

原則は、ゲームディレクターの立場で語られた内容をもとにしている。次の原則は、そのまま当てはめずに読み替える。

- **製品・市場寄りの原則（P01a・P07a・P12a・P18a）**: 元はゲーム製品と市場の話である。ソフトウェア開発に使うときは、
  「利用者」「遊ぶ人」を、そのソフトウェアを使う人や呼び出す側に置き換える。置き換えたことを明記する
- **決める人を前提にした原則（P04b・P11a・P15a・P17a）**: ユーザーが決める立場か、提案する立場かを先に確かめる
  - 決める立場なら、原則をそのまま使う
  - 提案する立場なら、「決める人が判断しやすい材料になっているか」に置き換える
  - レビューでは、成果物に「この決定は誰が決めたか」が書かれているかを問う
