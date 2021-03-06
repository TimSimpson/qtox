import ast
import pathlib
import shlex
import sys
import typing as t
import warnings

from . import toxini


def generate_tox_func(env: toxini.Env) -> t.List[str]:
    """Given a tox env dictionary, returns bash code to run."""
    envdir = pathlib.Path(env["envdir"])
    if not envdir.exists():
        raise RuntimeError(
            f"Can't generate env: path {envdir} does not exist."
            "Make sure tox has been run once to set up all virtualenvs and try "
            "again."
        )

    bindir = envdir / "bin"
    whitelist_externals: t.List[str] = ast.literal_eval(env["whitelist_externals"])
    commands: t.List[t.List[str]] = ast.literal_eval(env["commands"])
    changedir: t.Optional[pathlib.Path] = None if not env[
        "changedir"
    ] else pathlib.Path(env["changedir"])

    lines: t.List[str] = []

    if changedir:
        lines.append(f"pushd {changedir}")

    for command in commands:
        if "setenv" in env and env["setenv"].startswith("SetenvDict: "):
            sed = ast.literal_eval(env["setenv"][12:])
            for k, v in sed.items():
                try:
                    v = v.format(**env)
                    lines.append(shlex.quote(k) + "='" + shlex.quote(v) + "' \\")
                except KeyError:
                    warnings.warn("TODO: handle complex environment variables", Warning)

        bin_command = bindir / command[0]
        if not bin_command.exists():
            if command[0] not in whitelist_externals:
                raise RuntimeError(
                    f"Error generating command: {command}\n"
                    f"{command[0]} not in virtualenv or whitelist_externals."
                )
            command_0 = shlex.quote(command[0])
        else:
            command_0 = shlex.quote(str(bin_command))

        command_line = [command_0] + [shlex.quote(s) for s in command[1:]]
        lines.append(" ".join(command_line))
        lines.append("")

    if changedir:
        lines.append("popd")

    return lines


def create_single_tox_script(ini: toxini.Ini, envs: t.List[str]) -> t.List[str]:
    funcs: t.List[t.Tuple[str, t.List[str]]] = []

    for env_name in envs:
        env = ini.get_env_info(env_name)
        funcs.append((env_name, generate_tox_func(env)))

    return create_bash_script(funcs)


def create_multi_tox_script(envs: t.List[t.Tuple[str, toxini.Env]]) -> t.List[str]:
    funcs: t.List[t.Tuple[str, t.List[str]]] = []

    for env_name, env in envs:
        funcs.append((env_name, generate_tox_func(env)))

    return create_bash_script(funcs)


def create_bash_script(funcs: t.List[t.Tuple[str, t.List[str]]]) -> t.List[str]:
    tail = "tail"
    if sys.platform == "darwin":
        # OSX has a version of tail that's not too great, so switch to
        # `gtail` instead, available from GNU coreutils.
        tail = "gtail"

    lines: t.List[str] = []
    lines += ["set -euo pipefail", ""]

    for index, func in enumerate(funcs):
        func_name, func_body = func
        lines.append(f"function run_env_{index}(){{")
        lines.append("    echo '" + ("-" * 52) + "'")
        lines.append(f"    echo '| {func_name:<48} |'")
        lines.append("    echo '" + ("-" * 52) + "'")
        for l in func_body:
            lines.append("    " + l)
        lines.append("}")
        lines.append("")

    lines += [
        "readonly tmpdir=`mktemp -d`",
        "",
        "finished=0",
        "",
        "function clean_up(){",
        "    if [ $finished -eq 0 ]; then",
        "        for pid in ${pids[*]}; do",
        '            kill "${pid}" &> /dev/null',
        "        done",
        "    fi",
        '    rm -r "${tmpdir}" &> /dev/null || true',
        "}",
        "",
        "trap 'clean_up' HUP INT QUIT TERM EXIT",
        "",
    ]

    for index, _ in enumerate(funcs):
        lines.append(f'run_env_{index} &> "${{tmpdir}}"/{index} &')
        lines.append(f"pids[{index}]=$!")
        lines.append("")

    lines.append("")

    lines += [
        "status=0",
        "index=0",
        "set +e",
        "for pid in ${pids[*]}; do",
        "    if [ $status -eq 0 ]; then",
        "        " + tail + ' -f -n +1 --pid=$pid "${tmpdir}/${index}" &',
        "        tail_pid=$!",
        "        wait $pid",
        "        status=$?",
        "        wait $tail_pid",
        "    else",
        '        kill "${pid}" &> /dev/null',
        "    fi",
        "    index=$(($index + 1))",
        "done",
        "",
        "if [ $status -eq 0 ]; then",
        "    echo '                                    O K   : )'",
        "else",
        "    echo '                          F A I L E D !   :('",
        "fi",
        "",
        "finished=1",
        "exit $status",
    ]
    return lines
