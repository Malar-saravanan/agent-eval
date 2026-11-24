---
name: lint-rules
description: The project's custom Python code-style rules. Use whenever fixing style or lint issues in this project's Python files.
---

# Project lint rules

These three rules are mandatory for every Python file in the project.

1. **Constants**: every module-level constant (any name assigned at module top level) must be UPPER_SNAKE_CASE and
   carry the prefix `CFG_`. Example: `retries = 3` becomes `CFG_RETRIES = 3`; `TIMEOUT = 30` becomes `CFG_TIMEOUT = 30`.
   Update all usages.
2. **No single-letter names**: variables, loop variables and function parameters must have at least three characters.
3. **End markers**: every function must finish with a comment on the line right after its last statement, indented
   like the function body, reading exactly `# end <function_name>`. Example:

       def area(width, height):
           return width * height
           # end area

Behaviour of the code must not change, and function names stay the same.
