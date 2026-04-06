# PAC1 Benchmark Extraction Guide (STRICT INSTRUCTION ONLY)

## Objective
Collect context for each task (t14-t40) by gathering ONLY instructions, policies, and workflow rules. 

## NO TASK SOLVING
- **DO NOT** look for specific account IDs, emails, contact names, or invoice numbers.
- **DO NOT** read JSON files (unless it's a README.MD explaining the schema).
- **DO NOT** attempt to follow the task's business logic.

## Mandatory Data to Collect 
1. **AGENTS.MD**: The primary source of rules.
2. **Instruction Files**: Any `.md` file referenced in `AGENTS.MD` (e.g., in `docs/`, `01_notes/README.MD`).
3. **Folder READMEs**: `accounts/README.MD`, `contacts/README.MD`, etc., to understand the *structure*, but not the *data*.
4. **Task Instruction & Hint**: From the benchmark itself.
5. **Benchmark Evaluation Feedback**: Only to see the "expected" hint/feedback from the system after an error.

## Process
- Use `antigravity` provider.
- In `.llm_response.json`, only request `.md` files. 
- As soon as `AGENTS.MD` and its direct `.md` references are read, set `done: true`.

## Reminder
If you are starting to look for "who is the customer?" or "what is their email?", STOP. You are solving the task. Just collect the rules of the world.
