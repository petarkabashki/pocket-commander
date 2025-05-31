## Project gguidelines

- Always use 'conda activate py312' before running python in the terminal
- Use '&&' instead of '&amp;&amp;' in terminal commands
- Keep source files under 350 lines of code, refactor if needed to enforce that
- Always implement comprehensive debugging for trouble shooting in pocketflow nodes, tools and flows
- Use yaml format for tool calling and structured input and output to llms.

### In the pocket_commander package folder:
  - Put new nodes in individual files under 'nodes' folder
  - Put node tools in individual files under 'tools' folder
  - Put individual pocketflow flow composition functions under 'flows'
  - Put generic utilities under 'utilities'