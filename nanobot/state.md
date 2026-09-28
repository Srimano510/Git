By combining a structured `state.md` tracker with atomic Git commits, any agent (whether interrupted by token limits, timeout errors, or crashes) can inspect the current state, roll back unfinished intermediate changes, and resume execution seamlessly.

---

## 1. `state-log.md` Template

Place this file in the root of your project directory. It serves as the single source of truth for all working AI agents.

```markdown
# Agent Execution State

## Session Metadata
- **Goal**: Implement JWT Authentication & User Login
- **Initial Commit ID**: `a1b2c3d4e5f6`
- **Current Status**: IN_PROGRESS # Options: PENDING | IN_PROGRESS | COMPLETED | FAILED
- **Last Active Step**: Step 2

## Task Checklist
- [x] Step 1: Install JWT dependencies and create utility helper
- [/] Step 2: Implement `/login` and `/refresh` API endpoints
- [ ] Step 3: Add authentication middleware for protected routes
- [ ] Step 4: Write unit tests for auth flow

## Execution Log
| Step | Task Description | Status | Commit Hash | Timestamp |
| :--- | :--- | :--- | :--- | :--- |
| Start | Session Initialized | SUCCESS | `a1b2c3d4e5f6` | 2026-09-28T18:00:00Z |
| Step 1 | Install JWT dependencies & helper | SUCCESS | `b2c3d4e5f6a7` | 2026-09-28T18:02:15Z |
| Step 2 | Implement `/login` & `/refresh` endpoints | RUNNING | `c3d4e5f6a7b8` | 2026-09-28T18:05:10Z |

## Final Delivery Record
- **Start Commit ID**: `a1b2c3d4e5f6`
- **End Commit ID**: `PENDING`

```

---

## 2. Agent Execution Protocol

To make this system work across independent prompt executions, any agent must follow this 4-phase lifecycle every time it is invoked:

```
                  ┌─────────────────────────────────┐
                  │      Agent Run Initiated        │
                  └────────────────┬────────────────┘
                                   │
                                   ▼
                  ┌─────────────────────────────────┐
                  │   Phase 1: Read state.md        │
                  │   Check for incomplete work     │
                  └────────────────┬────────────────┘
                                   │
                 Is last step status "RUNNING"?
                        │                     │
                     [ Yes ]               [ No ]
                        │                     │
                        ▼                     ▼
        ┌──────────────────────────────┐  ┌───────────────────────────┐
        │ Roll back working directory  │  │ Identify next pending task│
        │ git reset --hard <last_good> │  └─────────────┬─────────────┘
        └──────────────┬───────────────┘                │
                       └────────────────────────────────┘
                                   │
                                   ▼
                  ┌─────────────────────────────────┐
                  │   Phase 2: Execute Task Step    │
                  │   Mark [/] in state.md          │
                  │   Make changes & git commit     │
                  │   Mark [x] in state.md          │
                  └────────────────┬────────────────┘
                                   │
                                   ▼
                  ┌─────────────────────────────────┐
                  │ Phase 3: Check Checkmarks       │
                  └────────────────┬────────────────┘
                                   │
                   Are ALL checkmarks satisfied?
                        │                     │
                     [ Yes ]               [ No ]
                        │                     │
                        ▼                     ▼
        ┌──────────────────────────────┐  ┌───────────────────────────┐
        │ Phase 4: Verification &      │  │ Exit / Wait for next step │
        │ Git Squash to single commit  │  └───────────────────────────┘
        └──────────────────────────────┘

```

### Phase 1: Pre-check & Error Recovery (Rollback)

1. Read `state.md` before executing any code.
2. Check the `Execution Log` for the last logged action:
* **If the last action has `Status: RUNNING**` (meaning the previous session crashed mid-step):
* Identify the last known good commit hash (`Commit Hash` from the previous `SUCCESS` step).
* Run: `git reset --hard <last_successful_commit_hash>`
* Update `state.md` to remove the failed entry and set `Current Status: IN_PROGRESS`.


* **If the last action was `SUCCESS**`: Resume directly from the next unchecked task (`[ ]`).



### Phase 2: Step Execution & Step Committing

For each task item in the checklist:

1. Update `state.md`: Mark task as `[/]` (in progress) and set log status to `RUNNING`.
2. Perform the required code/file modifications.
3. Stage and commit the step:
```bash
git add .
git commit -m "step(auth): implement step 2 login endpoints"

```


4. Record the resulting commit hash into `state.md` and mark the task checkmark as `[x]` (completed).
5. Commit the updated `state.md` so the state file remains in sync with the git tree.

### Phase 3: Task Checklist Verification

Before finishing the session, parse `state.md` to confirm every task checkmark is satisfied (`[x]`).

* **If items remain unchecked (`[ ]`)**: Stop and prompt for the next turn, or continue to the next task if tokens permit.

### Phase 4: Final Commit Squashing

When **all checkmarks** in `state.md` are verified as `[x]`:

1. Retrieve `Initial Commit ID` from `state.md` (e.g., `a1b2c3d4e5f6`).
2. Soft reset all intermediate step commits back to the starting point:
```bash
git reset --soft a1b2c3d4e5f6

```


3. Create a single, clean implementation commit:
```bash
git commit -m "feat(auth): implement JWT auth endpoints and middleware"

```


4. Capture the new final commit ID (e.g., `z9y8x7w6v5u4`).
5. Update `state.md`:
* Set `Current Status: COMPLETED`.
* Set `End Commit ID: z9y8x7w6v5u4`.


6. Make a final commit for `state.md` (or leave it committed alongside the squashed work).

---

## 3. How to Configure This for Agents

You have two primary ways to enforce this behavior:

### Option A: Repository Rules File (Pure Prompting)

Create an instruction file in the project root named `AGENTS.md`, `.cursorrules`, or `CLAUDE.md` containing the following system protocol:

```markdown
# Agent Execution Protocol

Before taking ANY action or making file changes:
1. Open and read `state.md`.
2. Check `Execution Log`. If any entry is marked `RUNNING`, run `git reset --hard <last_SUCCESS_commit>` and clean up state.md before proceeding.
3. If no work has started, record the current HEAD commit hash as `Initial Commit ID` in `state.md`.
4. Work through tasks in `Task Checklist` sequentially:
   - Mark task `[/]` while working.
   - Commit changes after completing each step with a brief commit message.
   - Log the step commit hash and mark `[x]` upon completion.
5. Once ALL checkmarks are `[x]`:
   - Execute `git reset --soft <Initial Commit ID>`.
   - Create a squashed commit: `git commit -m "<type>: <brief description>"`.
   - Record the final commit ID in `state.md` and set `Current Status: COMPLETED`.

```

### Option B: Automated Shell / Python Orchestration Script

If you want total control over git execution (preventing the LLM from forgetting to commit or reset), you can run a lightweight wrapper script around your agent CLI (e.g., `cline`, `claude`, or custom OpenAI API script).