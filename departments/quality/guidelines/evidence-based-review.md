# guideline: evidence-based-review
## 触发条件
关键词: review, 验收, 检查, 审查, diff, commit
## 规则
- 必须自行 git diff 查看实际代码改动
- 不要仅依赖工部的输出摘要
- 检查改动是否引入了新的 lint 错误或语法问题
- 如果有测试，先跑测试
