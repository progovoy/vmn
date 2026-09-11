# Renders demo/vmn-goto.gif with VHS (https://github.com/charmbracelet/vhs).
#
#   demo/setup.sh            # builds /tmp/vmn-demo
#   vhs demo/demo.tape       # run from the repo root, with vmn on PATH
#
Output demo/vmn-goto.gif

Set Shell bash
Set FontSize 16
Set Width 1100
Set Height 600
Set Theme "Catppuccin Mocha"
Set TypingSpeed 40ms
Set Padding 20

Env GIT_AUTHOR_NAME "demo"
Env GIT_COMMITTER_NAME "demo"
Env GIT_AUTHOR_EMAIL "demo@example.com"
Env GIT_COMMITTER_EMAIL "demo@example.com"

Hide
Type "export PS1='$ ' PROMPT_COMMAND= VIRTUAL_ENV_DISABLE_PROMPT=1; cd /tmp/vmn-demo/work/shop && clear" Enter
Show

Type "# shop depends on ../lib_core and ../service_api. Release it:" Enter
Sleep 500ms
Type "vmn stamp -r minor shop" Enter
Sleep 2.5s

Type "# lib_core and shop each get a new commit, then release again:" Enter
Hide
Type "perl -pi -e s/off/on/ ../lib_core/core.py; tput cuu1; tput el" Enter
Sleep 500ms
Show
Type "git -C ../lib_core commit -qam 'feat: enable fast path' && git -C ../lib_core push -q" Enter
Sleep 1s
Hide
Type "echo 'USE_V2 = True' >> shop.py; tput cuu1; tput el" Enter
Sleep 500ms
Show
Type "git commit -qam 'feat: use v2 orders' && git push -q" Enter
Sleep 1s
Type "vmn stamp -r minor shop" Enter
Sleep 2.5s

Type "# A bug report comes in for 0.1.0. Which lib_core was it built with?" Enter
Sleep 500ms
Type "git -C ../lib_core log --oneline -1 && cat ../lib_core/core.py" Enter
Sleep 2.5s

Type "vmn goto -v 0.1.0 shop" Enter
Sleep 3s
Type "git -C ../lib_core log --oneline -1 && cat ../lib_core/core.py" Enter
Sleep 3s

Type "# Every repo is back at the revision recorded in the release tag." Enter
Sleep 500ms
Type "vmn goto -v 0.2.0 shop" Enter
Sleep 4s
