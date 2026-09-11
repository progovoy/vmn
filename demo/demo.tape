# Renders demo/vmn-goto.gif with VHS (https://github.com/charmbracelet/vhs).
#
#   demo/setup.sh            # builds /tmp/vmn-demo
#   vhs demo/demo.tape       # run from the repo root, with vmn on PATH
#
Output demo/vmn-goto.gif

Set Shell bash
Set FontSize 15
Set Width 1100
Set Height 700
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms
Set Padding 20

Env GIT_AUTHOR_NAME "demo"
Env GIT_COMMITTER_NAME "demo"
Env GIT_AUTHOR_EMAIL "demo@example.com"
Env GIT_COMMITTER_EMAIL "demo@example.com"

Hide
Type "export PS1='$ ' PROMPT_COMMAND= VIRTUAL_ENV_DISABLE_PROMPT=1; cd /tmp/vmn-demo/work/shop && clear" Enter
Show

Type "# shop tracks two dependency repos and writes its version into version.py" Enter
Type "cat .vmn/shop/conf.yml" Enter
Sleep 4s

Type "vmn stamp -r minor shop && cat version.py" Enter
Sleep 2.5s

Type "clear" Enter
Type "# Only a dependency changes. shop itself is untouched:" Enter
Hide
Type "perl -pi -e s/off/on/ ../lib_core/core.py; tput cuu1; tput el" Enter
Sleep 500ms
Show
Type "git -C ../lib_core commit -qam 'feat: enable fast path' && git -C ../lib_core push -q" Enter
Sleep 1s
Type "vmn stamp -r minor shop && cat version.py" Enter
Sleep 2.5s

Type "# A bug report comes in for 0.1.0. Restore that exact state:" Enter
Type "vmn goto -v 0.1.0 shop" Enter
Sleep 3s
Type "cat version.py ../lib_core/core.py" Enter
Sleep 4s
