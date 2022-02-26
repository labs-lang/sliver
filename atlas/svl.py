from pathlib import Path
import platform
from cli import SliverError


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


def exp_main(has_stigmergy, has_env, num_agents, not_hidden):
    r_r = "refresh, request"
    ge_se = "getenv, setenv"
    gates = r_r if has_stigmergy else ""
    agents = "\n  ||\n".join(
        exp_agent(has_stigmergy, has_env, not_hidden, i)
        for i in range(num_agents))

    if has_stigmergy and has_env:
        gates += ", "
    if has_env:
        gates += ge_se

    def prio(gate):
        return " > ".join(f'"{gate} !{i} .*"' for i in range(num_agents))

    prios = f"""
    total prio
        "ATTR .*" > "REFRESH .*" > "L .*" > "REQUEST .*"
        {prio("ATTR")}
        {prio("L")}
        {prio("REQUEST")}
    in""" if has_stigmergy else ""

    return f"""
{"par" if has_stigmergy or has_env else ""}
{r_r +" -> MatrixStorage ["+ r_r +", debug]" if has_stigmergy else ""}
{"||" if has_stigmergy else ""}
{"getenv, setenv -> Env [getenv, setenv]" if has_env else ""}
{"||" if has_env else ""}
{gates}{" -> " if gates else ""}
    ({prios if has_stigmergy else ""}
    par tick{", put, qry" if has_stigmergy else ""} in
    {agents}
    end par
    {"end prio)" if has_stigmergy else ""}
{"end par" if has_stigmergy or has_env else ""}
"""


def svl(fname, not_hidden, has_stigmergy, has_env, num_agents):
    with open(fname) as f:
        lines = f.readlines()
    start = next(
        (i+1 for i, l in enumerate(lines) if "process main" in l),
        None)
    if start is None:
        raise SliverError("Generation of SVL script has failed.")
    end = next((
        i for i, l in enumerate(lines[start:], start)
        if "end process" in l), -1)
    main = "".join(lines[start:end])

    return f"""
% CADP_TIME={"/usr/bin/time" if "Linux" in platform.system() else "gtime"}

% DEFAULT_PROCESS_FILE="{fname}"

"{fname}.bcg" = root leaf sharp reduction
hold "request", "refresh", "l", "attr"
of
(
   hide all but SPURIOUS, {", ".join(not_hidden) if not_hidden else ""} in
{exp_main(has_stigmergy, has_env, num_agents, not_hidden)}
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
