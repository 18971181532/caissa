# 示例

两份可以直接喂给 `caissa pgn`（或 `run_demos.py pgn`）的历史名局，用来验证
PGN 解析、SAN 消歧和将杀判定。两局都能一路解析到最后的 `#`，中间没有一步
被跳过——如果棋规实现有错，通常在前十步就会露馅。

| 文件 | 对局 | 步数 | 看点 |
| --- | --- | --- | --- |
| `opera-game.pgn` | Morphy — 布伦瑞克公爵与伊苏阿尔伯爵，巴黎 1858 | 33 | 全部子力参与进攻；连续弃后；`Rd8#` |
| `immortal-game.pgn` | Anderssen — Kieseritzky，伦敦 1851 | 45 | 双象与双马同时悬空；`Be7#` |

```bash
python run.py pgn --in examples/opera-game.pgn
python run.py pgn --in examples/immortal-game.pgn
```

两局都收录在公共领域，记谱取自通行的 PGN 版本。
