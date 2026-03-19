# guideline: multi-file
## Trigger Conditions
Keywords: multiple files, refactor, across files
## Rules
- List all files to be modified and the intent of each change before starting
- Modify in dependency order (dependencies first)
- After modifying each file, confirm there are no syntax errors
- If an interface signature is changed, grep all callers to verify consistency
