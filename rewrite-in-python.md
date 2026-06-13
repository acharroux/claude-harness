# Brief rewrite the harness orchestration scripts in Python

This harnes is very powerful and has 2 modes:
 - used with skills: /harness-run, /harness-fix,...
 - used with the harness orchestration script: harness/orchestrate.sh <task> <plenty of options>

Using skills directly is very good but orchestrations script is supposed to be the most powerful (cf files README.md and and docs\What Happens When You Trust an Agent With a Long Build.md)

Issue is using the orchestrate.sh on Windows is very difficult : this is a bash script, at best it switches to wsl and then have other intricated pbms.


So, I asked to rewrite the harness orchestration scripts in Native PowerShell.
This has been tough but it has been done (cf all .ps1 files).
There is test system in place for testing and validating the orchestration script but this system is definitely not compatible with Windows. so the port to powershell does NOT include this tests system and lack validation process.

So, it works **globally**. Globally because after hours of work, some errors are popping. Precisely the kind of errors that would have detected by a proper test system of orchestration script (plenty of options to validate).

So at this time, we have
- an orchestration.sh script that works on Linux and MacOS. With full tests system and validation process of the script.
- an orchestration.ps1 script that works globally on Windows. 
    - Without tests system and validation process of the powershell script and there are still some corner-case issues that pop up. Typically at end of works, after hours of work, which is specially ennoying
    - Code is entirely duplicated in bash and powershell. Any work on it will need to be done 2 times.

## Use python to rewrite the harness orchestration scripts
Using woud give us:
 - A single code base for the orchestration script, which would be cross-platform (Linux, MacOS, Windows).
 - access to a tests system that could probably be a translation of bats tests in windows
 - requirements for the orchestration script could disappear. .sh needs jql and bats for tests. Maybe everything can be done in python, including tests system. So no more requirements for the orchestration script ther than python and a few modules.

## Technical details

- you should start by studying 
    - the documentation: README.md docs\What Happens When You Trust an Agent With a Long Build.md
    - harness/orchestrate.sh script and all dependant scripts and functions.
    - the test system (including the bats tests) and how it works.
- understand what are the actual requirements for the orcheastrate script and dependencies to work. I have identified jql and bats as requirements for the bash script. Maybe there are others.
- a key point: are the skills calling part of the orchestration scripts ? If yes, this must be clearly identified so the skills can be changed to call the new python system

I suggest to not build a monolithic python script but keep a set of modules mimicking the current decomposition in .sh scripts which is well done and easier to maintain.

**Important: **

- NEVER modify the .sh scripts, neither the .ps1 scripts. They are working and should remain working. The goal is to rewrite them in python, not to modify them.
- NEVER modify the skills other than to make them call the new python orchestration script instead of the .sh. Such change should be minimal and only to redirect the call. The skills are working and should remain working. The goal is to rewrite the orchestration scripts in python, not to modify the skills

## Proof
The test system described in the README.md file should work with the new python orchestration script. This would be a proof that the python script is working as expected and is equivalent to the bash script.