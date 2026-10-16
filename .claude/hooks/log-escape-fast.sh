# log-escape-fast.sh -- sourced by log-escape.sh. Defines fast().
#
# fast() fills in, ahead of log-escape.sh's pipelines, the values they would
# produce, and sets FAST=1. It sets FAST only when every value is exactly what
# the pipelines give; otherwise the pipelines run as before. In order:
#   1. shell_fast: a Bash/PowerShell call whose JSON this file can read as jq
#      would, and whose command shell-scope.py certainly passes -- no process;
#   2. log-escape.py: one Python process for everything else it can answer;
#   3. nothing: FAST stays empty.
# Everything below fast() runs as an `if` condition, where set -e is off, so
# no test here can end the hook. Every variable is set before it is read.

fast() {
  hash jq tr sed 2>/dev/null || return 0  # a missing tool is the pipelines' failure
  case "$TOOL" in
    Bash|PowerShell) if shell_fast; then FAST=1; return 0; fi ;;
  esac
  # Through run-python.sh, never a bare `python`: a host with only `python3`, or
  # whose `python` is too old, lost every line this answers (lane 6177).
  OUT="$(exec bash "$ROOT/.claude/hooks/run-python.sh" "$ROOT/.claude/hooks/log-escape.py" "$TOOL" <<<"$INPUT" 2>/dev/null)" || return 0
  if [[ "$OUT" == "#log-escape"$'\n'*$'\n'"FAST=1" ]]; then eval "$OUT"; fi
}

# shell_fast: RAW, SCAN and SS_LINE for a Bash call, or status 1 when unsure.
shell_fast() {
  # This reader copies the rest of a string at every escape, so it costs size x
  # escapes: a 75 KB tool_response ran past the hook's 10 s timeout and logged
  # nothing (SE review F1). Past these caps log-escape.py is cheaper, and linear.
  input_bytes 2>/dev/null
  if [ "$BYTES" -gt 12288 ]; then return 1; fi
  local bs=${INPUT//[!\\]/}
  if [ ${#bs} -gt 400 ]; then return 1; fi
  local sur='\\u[dD][89a-fA-F]' nl=$'\n' src
  # A UTF-16 surrogate escape anywhere is a jq parse error (1.7) or U+FFFD (1.6).
  if [[ $INPUT =~ $sur ]]; then return 1; fi
  json_command || return 1
  if [ "$JSET" != 1 ]; then       # null, false or absent: `// empty`
    RAW=""; SCAN=""; SS_LINE=""; return 0
  fi
  # ASCII and no \u: the decoded text is byte-for-byte what jq prints, and
  # shell-scope's regexes (IGNORECASE, \w, \s) read it the ASCII way.
  if [[ $JCMD == *[![:ascii:]]* || $JCMD == *\\u* ]]; then return 1; fi
  jdecode "$JCMD"
  ss_quiet "$DEC" || return 1
  RAW=${DEC//$'\r'/}              # | tr -d '\r'
  while [[ $RAW == *"$nl" ]]; do RAW=${RAW%"$nl"}; done   # $( ) strips these
  src=${RAW//\\$nl/ }
  src=${src//$nl/;}
  blank "$src"
  SCAN=$BL
  SS_LINE=""
  return 0
}

# input_bytes: BYTES gets INPUT's length in bytes. Under a UTF-8 locale ${#INPUT}
# counts characters, and 35 KB of em-dashes passed a 12 KB cap; the
# local LC_ALL is undone when this returns. Undoing an uninstalled LC_ALL prints
# a setlocale warning, so the caller sends this function's stderr to /dev/null.
# A probe for multibyte locales misread Shift_JIS.
input_bytes() {
  local LC_ALL=C
  BYTES=${#INPUT}
}

# json_command: read INPUT as strict JSON (a subset of what jq accepts) and set
# JCMD to the still-escaped text of .tool_input.command, JSET=1 when that is a
# string. Status 1 for anything else: a shape jq would reject or print as JSON,
# a key that only decodes to tool_input or command, too deep, too many tokens.
json_command() {
  local s=$INPUT ws=$' \t\n\r' lead c want=value key="" stack="" tiobj=0 n=0 role num
  local numre='^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?'
  JCMD=""; JSET=0
  while :; do
    lead=${s%%[!$ws]*}; s=${s:${#lead}}
    if [ -z "$s" ]; then
      [ "$want" = end ] && return 0
      return 1
    fi
    n=$((n + 1))
    if [ $n -gt 400 ]; then return 1; fi
    c=${s:0:1}
    case $want in
      end) return 1 ;;
      colon)
        [ "$c" = : ] || return 1
        s=${s:1}; want=value; continue ;;
      next)
        if [ "$c" = , ]; then
          s=${s:1}
          if [ "${stack: -1}" = o ]; then want=key; else want=value; fi
          continue
        fi
        jclose || return 1; continue ;;
      key|key1)
        if [ "$c" = '}' ] && [ $want = key1 ]; then jclose || return 1; continue; fi
        [ "$c" = '"' ] || return 1
        jstr || return 1
        key=$TOK
        if [ ${#stack} -eq 1 ] || { [ ${#stack} -eq 2 ] && [ $tiobj = 1 ]; }; then
          if [[ $key == *\\* ]]; then return 1; fi   # might decode to a name we track
        fi
        want=colon; continue ;;
    esac
    # A value. Which one: tool_input itself, its command, or neither.
    if [ "$want" = value1 ] && [ "$c" = ']' ]; then jclose || return 1; continue; fi
    role=""
    if [ ${#stack} -eq 0 ]; then
      [ "$c" = '{' ] || return 1                     # jq errors indexing a non-object
    elif [ "${stack: -1}" = o ]; then
      if [ ${#stack} -eq 1 ] && [ "$key" = tool_input ]; then role=ti
      elif [ ${#stack} -eq 2 ] && [ $tiobj = 1 ] && [ "$key" = command ]; then role=cmd
      fi
    fi
    case $c in
      '{')
        [ "$role" = cmd ] && return 1
        if [ "$role" = ti ]; then JCMD=""; JSET=0; tiobj=1; fi   # the last tool_input wins
        stack+=o; s=${s:1}; want=key1
        if [ ${#stack} -gt 64 ]; then return 1; fi
        continue ;;
      '[')
        [ -n "$role" ] && return 1
        stack+=a; s=${s:1}; want=value1
        if [ ${#stack} -gt 64 ]; then return 1; fi
        continue ;;
      '"')
        [ "$role" = ti ] && return 1
        jstr || return 1
        if [ "$role" = cmd ]; then JCMD=$TOK; JSET=1; fi ;;
      n)
        [ "${s:0:4}" = null ] || return 1
        s=${s:4}
        if [ -n "$role" ]; then JCMD=""; JSET=0; fi ;;
      f)
        [ "${s:0:5}" = false ] || return 1
        [ "$role" = ti ] && return 1
        s=${s:5}
        if [ "$role" = cmd ]; then JCMD=""; JSET=0; fi ;;
      t)
        [ "${s:0:4}" = true ] || return 1
        [ -n "$role" ] && return 1
        s=${s:4} ;;
      -|[0-9])
        [ -n "$role" ] && return 1
        [[ ${s:0:64} =~ $numre ]] || return 1
        num=${#BASH_REMATCH[0]}
        if [ "$num" -eq 0 ] || [ "$num" -ge 64 ]; then return 1; fi
        s=${s:num} ;;
      *) return 1 ;;
    esac
    want=next
  done
}

# jclose: s starts with `}` or `]`; it must close the innermost container.
jclose() {
  local c=${s:0:1}
  if [ "$c" = '}' ] && [ "${stack: -1}" = o ]; then :
  elif [ "$c" = ']' ] && [ "${stack: -1}" = a ]; then :
  else return 1; fi
  stack=${stack%?}; s=${s:1}
  if [ ${#stack} -eq 1 ]; then tiobj=0; fi
  if [ -z "$stack" ]; then want=end; else want=next; fi
  return 0
}

# jstr: s starts with `"`; TOK gets the string's text still escaped, s moves past it.
jstr() {
  local r=${s:1} pre e
  TOK=""
  while :; do
    pre=${r%%[\"\\]*}
    [ ${#pre} -eq ${#r} ] && return 1            # unterminated
    TOK+=$pre; r=${r:${#pre}}
    if [ "${r:0:1}" = '"' ]; then s=${r:1}; break; fi
    e=${r:1:1}
    case $e in
      [\"\\/bfnrt]) TOK+=${r:0:2}; r=${r:2} ;;
      u)
        [[ ${r:2:4} == [0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F] ]] || return 1
        TOK+=${r:0:6}; r=${r:6} ;;
      *) return 1 ;;
    esac
  done
  if [[ $TOK == *[[:cntrl:]]* ]]; then return 1; fi   # jq rejects raw controls
  return 0
}

# jdecode <escaped text, no \u>: DEC gets the string jq would print.
jdecode() {
  local r=$1 pre e
  DEC=""
  while [[ $r == *\\* ]]; do
    pre=${r%%\\*}; e=${r:${#pre}+1:1}; r=${r:${#pre}+2}
    DEC+=$pre
    case $e in
      n) DEC+=$'\n' ;; t) DEC+=$'\t' ;; r) DEC+=$'\r' ;;
      b) DEC+=$'\b' ;; f) DEC+=$'\f' ;; *) DEC+=$e ;;
    esac
  done
  DEC+=$r
}

# blank <text>: BL gets log-escape.sh's sed blanker applied to text, which has
# no newline: s/'[^']*'|"[^"]*"/ /g, leftmost match first.
blank() {
  local r=$1 pre q
  BL=""
  while :; do
    pre=${r%%[\"\']*}
    if [ ${#pre} -eq ${#r} ]; then BL+=$r; break; fi
    q=${r:${#pre}:1}; r=${r:${#pre}+1}
    if [[ $r == *"$q"* ]]; then
      BL+="$pre "; pre=${r%%"$q"*}; r=${r:${#pre}+1}
    else
      BL+="$pre$q"                  # no partner: sed moves on one character
    fi
  done
}

# ss_quiet <ASCII command>: status 0 only when shell-scope.py --log certainly
# prints nothing for it -- no write verb, no sed -i, no truncate, and every `>`
# either `>&` or, when no heredoc could move text, a redirect to /dev/null.
# Checked on the whole command, which only over-reports against shell-scope's
# per-clause, heredoc-stripped reading (its boundaries are these, unchanged).
ss_quiet() {
  local t=$1 r=$1 pre dn='^>?[[:space:]]*/dev/null([[:space:];|&]|$)'
  local verbs='(^|[^[:alnum:]_./\-])(cp|copy-item|robocopy|mv|move-item|rename-item|out-file|set-content|add-content|tee-object|new-item|mkdir|md|tee|rm|del|rmdir|remove-item)([^[:alnum:]_-]|$)'
  local sedre='(^|[^[:alnum:]_])sed([^[:alnum:]_]|$)' loud=0
  while [[ $r == *'>'* ]]; do
    pre=${r%%'>'*}; r=${r:${#pre}+1}
    if [[ $r == '&'* ]]; then continue; fi
    if [[ $t != *'<<'* && $r =~ $dn ]]; then continue; fi
    return 1
  done
  shopt -s nocasematch
  if [[ $t =~ $verbs ]] || [[ $t == *truncate* ]]; then loud=1
  elif [[ $t =~ $sedre ]] && [[ $t == *-i* ]]; then loud=1
  fi
  shopt -u nocasematch
  return $loud
}
