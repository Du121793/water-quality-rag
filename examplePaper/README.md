# 如何放置論文與維護索引

本專案使用 RAG 系統，論文應按照類別進行組織。

## 檔案結構範例
```
papers/
├── category-a/
│   ├── 01_paper-title.pdf
│   ├── 02_another-paper.pdf
│   └── INDEX.md            <-- 該類別的論文清單說明
└── INDEX.md                <-- 全域論文目錄說明
```

## 步驟
1. **建立類別資料夾**：在 `papers/` 下建立一個描述性的資料夾名稱（如 `water-quality`）。
2. **放置 PDF**：將 PDF 檔案放入該資料夾，建議加上編號前綴以便排序。
3. **更新 INDEX.md**：
   - 每個資料夾內的 `INDEX.md` 應列出該目錄下的論文標題與簡介。
   - 根目錄的 `INDEX.md` 應列出所有類別。

## 注意事項
- 檔案名稱請避免使用特殊字元。
- 系統會自動掃描 `papers/` 資料夾進行索引與 Embedding 處理。
