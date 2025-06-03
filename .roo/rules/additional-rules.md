
When implementing pocketflow nodes, flows, tools and utils consult the pocketflow guidelines in:
    - docs/pocketflow-guides.md


## If you find a comment ending with 'AI!' use it as instruction to modify the code where the comment is or around it. Then remove the comment.

The Orchestrator:
    - Should provide all necessary context to subtasks so they don't have to read all the docs
    - Should explicity instruct the tasks not to read the cline_docs or to do so, if absolutely necessary
    - Can initiate hierarchical multi-level subtasks by calling smaller scale orchestrator tasks