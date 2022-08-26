from pathlib import Path
import platform

from ..app.cli import Args


def exp_agent(has_stigmergy, has_env, not_hidden, id_):
    hide = [x for x in ("ATTR", "L") if x not in not_hidden]
    hide = f"""hide {", ".join(hide)} in\n""" if hide else "\n"
    gates = "spurious, tick, attr"
    gates_l = ", put, qry, l, refresh, request" if has_stigmergy else ""
    gates_e = ", getenv, setenv" if has_env else ""
    return f"""
    {hide}agent [{gates}{gates_l}{gates_e}] (ID ({id_}))
    {"end hide" if hide else ""}
    """


def exp_main(has_stigmergy, has_env, num_agents, not_hidden, cli):
    gates = [
        "tick" if cli[Args.FAIR] else "",
        "refresh, request" if has_stigmergy else "",
        "getenv, setenv" if has_env else ""
    ]
    gates = ", ".join(g for g in gates if g)

    processes = [
        "tick -> sched [tick]" if cli[Args.FAIR] else "",
        "refresh, request -> Timestamps [refresh, request, debug]"
        if has_stigmergy else "",
        "getenv, setenv -> Env [getenv, setenv]" if has_env else "",
    ]
    processes = "\n||\n".join(p for p in processes if p)

    agents = "\n  ||\n".join(
        exp_agent(has_stigmergy, has_env, not_hidden, i)
        for i in range(num_agents))

    def prio(gate):
        return " > ".join(f'"{gate} !{i} .*"' for i in range(num_agents))

    prios = f"""
    total prio
        "ATTR .*" > "REFRESH .*" > "L .*" > "REQUEST .*"
        {prio("ATTR")}
        {prio("REFRESH")}
        {prio("L")}
        {prio("REQUEST")}
    in""" if has_stigmergy else ""

    return f"""
{"par" if processes else ""}
{processes if processes else ""}
{"||" if processes else ""}
{gates}{" -> " if gates else ""}
    ({prios if has_stigmergy else ""}
    par tick{", put, qry" if has_stigmergy else ""} in
    {agents}
    end par
    {"end prio)" if has_stigmergy else ""}
{"end par" if processes else ""}
"""


def svl(fname, not_hidden, has_stigmergy, has_env, num_agents, cli):

    return f"""
% CADP_TIME={"/usr/bin/time" if "Linux" in platform.system() else "gtime"}

% DEFAULT_PROCESS_FILE="{fname}"

"{fname}.bcg" = root leaf divsharp reduction
hold "REQUEST", "REFRESH", "L", "ATTR"
of
(
   hide all but SPURIOUS, {", ".join(not_hidden) if not_hidden else ""} in
{exp_main(has_stigmergy, has_env, num_agents, not_hidden, cli)}
   end hide
);

property CHECK
    "Compositional verification"
is
    "evaluator.bcg" = verify
    "{Path(fname).with_suffix(".mcl")}"
    with evaluator4
    in "{fname}.bcg";
    expected TRUE
end property

"""
