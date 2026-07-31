# Plans

Approved implementation plans, committed so cloud Devin sessions can read them.

Cloud sessions clone this repo in their own VM and cannot see the local working
tree or the terminal session a plan was produced in. A plan that lives only in
chat has to be re-typed into every child session's prompt, and those copies
drift. Committing it gives every child one canonical source.

## Flow

1. Plan interactively: `devin --model claude-5-fable-max`, then `megaplan <goal>`.
2. Answer its scope questions.
3. Approved plan lands here as `<slug>.md`, split into independent work-items.
4. Push, then spawn one cloud child per work-item, each told to read
   `.devin/plans/<slug>.md` and implement its assigned section only.

## Format

Each plan should carry a Work-items section where every item is independently
implementable — no item may depend on another item's uncommitted output, or the
children will conflict.
