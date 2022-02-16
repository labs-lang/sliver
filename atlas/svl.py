from pathlib import Path
import platform
from cli import SliverError


def svl(fname, not_hidden):
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

"{fname}.bcg" = root leaf divbranching reduction of
(
   hide all but SPURIOUS, {", ".join(not_hidden) if not_hidden else ""} in
{main}
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
