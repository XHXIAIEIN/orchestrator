# guideline: multi-file
## 触发条件
关键词: 多个文件, multiple files, 重构, refactor, 跨文件, across files
## 规则
- 先列出所有要改的文件和改动意图
- 按依赖顺序改（被依赖的先改）
- 每改完一个文件确认无语法错误
- 如果改了接口签名，grep 所有调用方确认一致性
