#!/bin/zsh
BIZHAWK_PATH=~/BizHawk
ROM_FILE='Pokemon - Yellow Version (UE) [C][!].gbc'
LUA_SCRIPT=poyo.lua

# based on EmuHawkMono.sh:
export LD_LIBRARY_PATH="$BIZHAWK_PATH/dll:$BIZHAWK_PATH:$LD_LIBRARY_PATH"
export MONO_CRASH_NOFILE=1
export MONO_WINFORMS_XIM_STYLE=disabled # see https://bugzilla.xamarin.com/show_bug.cgi?id=28047#c9
                                        # ^ very broken link
#DEBUG_OPTS=(--debug --debugger-agent=transport=dt_socket,server=y,address=127.0.0.1:55555)
#GDB_PREFIX=(gdb --args)
exec $GDB_PREFIX mono $DEBUG_OPTS "$BIZHAWK_PATH/EmuHawk.exe" ${ROM_FILE:a} --lua ${LUA_SCRIPT:a} --userdata poyo_path:$PWD --mmf "/dev/shm/poyo_screenshot.bin" --url-get http://127.0.0.1:25192 "$@"
