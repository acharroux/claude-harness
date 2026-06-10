# Brief generate Native PowerShell scripts in replacement of .sh ones

This repository provides a harness for Claude which is incredibly powerful and well working !
I have use only the skills (/harness-run,...) to build full projects, and I am very impressed by the results.

Issue is this harness is also usable with a set of .sh files that are even more powerful, but this is not possible to use them on Windows.
Things get messy with bash executed through wsl which search for native (natives in wsl) tools (like Claude itself), don't find it, try to go back to Windows, fails again,.  and some other obscure issues

So I need you to generate exactly the same set of .sh files but in Native PowerShell, with the same name but .ps1 extension, and with the same content but in PowerShell syntax.

## Resources

- CLAUDE.md
- README.md. the README.md is very complete and decrvbe all the scripts and their usage, so you can use it as a reference to understand what each script is doing and how to translate it into PowerShell.
- the README.md explains also how to smoke-test and validate the .sh scripts, so you can use it to ensure that the generated PowerShell scripts are working correctly using the same tests. All tests are provided in the folder named tests

I will use the skills to execute this task, not the harness scripts so there is no need to worry about a possible confusion between the scripts you are generating and the scripts you are using to generate them/

## Deliverables
I expect to have side to side with each .sh file a file with the same name but with .ps1 extension, and  but in PowerShell syntax. The generated PowerShell scripts should be fully functional and should be able to run on Windows without any issues and obviously do the same thing as the .sh scripts.

