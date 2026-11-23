# Renders docs/assets/boot.gif (about 10 seconds). Needs vhs: https://github.com/charmbracelet/vhs
#   vhs docs/assets/boot.tape
# The demo prints a fake briefing with generic names. It never calls Claude or reads your files.
Output docs/assets/boot.gif
Set Shell "bash"
Set FontSize 18
Set Width 1000
Set Height 520
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 60ms

Hide
Type "export PS1='$ ' && clear && alias claude='bash docs/assets/demo_boot.sh'"
Enter
Type "clear"
Enter
Show

Sleep 500ms
Type "claude"
Sleep 300ms
Enter
Sleep 9s
