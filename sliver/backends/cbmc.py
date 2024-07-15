#!/usr/bin/env python3
from dataclasses import dataclass
import os
from hashlib import sha1
import platform
from random import getrandbits
import re
import stat
import tempfile
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache, reduce
from importlib import resources
from operator import mul
from subprocess import (DEVNULL, PIPE, STDOUT, CalledProcessError,
                        check_output, run)

from lark import Lark

from ..app.cex import pprint_agent
from ..app.cli import Args, ExitStatus, SliverError
from ..app.info import get_var
from ..atlas.concretizer import Concretizer
from .common import Backend, BaseTransformer, Language, log_call


def to_cbmc_hex(numeric_string):
    return hex(int(numeric_string))[2:].upper()


class DimacsMapping:
    def __init__(self, file_obj):
        self.get_array = lru_cache(maxsize=128)(self._get_array)
        self.get_element = lru_cache(maxsize=128)(self._get_element)
        self.info = file_obj.readline().decode().strip()
        self.mapping = {}
        for ln in file_obj:
            ln = ln.decode()
            if ln[0] == "c":
                ln = ln.split(maxsplit=2)
                self.mapping[ln[1]] = ln[2]

    def __getitem__(self, key):
        item = self.mapping[key]
        if isinstance(item, list):
            return item
        self.mapping[key] = self._parse_vars(key, item)
        return self.mapping[key]

    def _parse_vars(self, name, vars_str):
        return tuple(
            x if x in ("FALSE", "TRUE") else int(x)
            for x in vars_str.split())

    def _get_element(self, name, indexes, dims):
        fmt_offset = "".join(f"[[{to_cbmc_hex(i)}]]" for i in indexes)
        try:
            # The easy way
            return self[name+"#2"+fmt_offset]
        except KeyError:
            # Bummer, we have to go the hard way
            pass
        try:
            arr = self[self.get_array(name)]
        except KeyError as e:
            raise e
        assert len(dims) > 0
        assert len(dims) == len(indexes)
        assert all(0 <= i < d for i, d in zip(indexes, dims))
        offset = indexes[-1]
        for x, idx in enumerate(indexes[:-1]):
            offset += idx * reduce(mul, dims[x+1:])
        # infer bitwidth from dimensions and size
        bw = len(arr) // reduce(mul, dims)
        start = bw * offset
        return arr[start:start+bw]

    def _get_array(self, name):
        """Find the first version of array "name" that is fully initialized"""
        def get_version(var_name):
            return int(var_name.split("#")[-1])

        candidates = [
            n for n in self.mapping
            if n.startswith(name) and "FALSE" not in self[n]]
        return min(candidates, key=get_version)


@dataclass
class State:
    state: int
    file: str
    function: str
    line: int
    lhs: str
    rhs: any


class CbmcCexTransformer(BaseTransformer):
    def state(self, n):
        header, lhs, rhs, *_ = n
        state_id, file, function, line, _ = header.children
        return State(state_id, file, function, line, lhs, rhs)


def translateCPROVER54(cex, info):
    with resources.path("sliver.grammars", "cbmc_cex.lark") as grammar_path:
        with open(grammar_path) as grammar:
            lark_parser = Lark(grammar,
                               parser='lalr',
                               start='start54',
                               transformer=CbmcCexTransformer())
    yield from translateCPROVER(cex, info, parser=lark_parser)


def translateCPROVERNEW(cex, info):
    with resources.path("sliver.grammars", "cbmc_cex.lark") as grammar_path:
        with open(grammar_path) as grammar:
            lark_parser = Lark(grammar,
                               parser='lalr',
                               transformer=CbmcCexTransformer())
    yield from translateCPROVER(cex, info, parser=lark_parser)


def translateCPROVER(cex, info, parser):
    ATTR = re.compile(r"I\[([0-9]+)l?\]\[([0-9]+)l?\]")
    LSTIG = re.compile(r"Lvalue\[([0-9]+)l?\]\[([0-9]+)l?\]")
    LTSTAMP = re.compile(r"Ltstamp\[([0-9]+)l?\]\[([0-9]+)l?\]")
    ENV = re.compile(r"E\[([0-9]+)l?\]")
    # STUFF = Word(printables)

    # TODO: fix property parser for "new" versions of CBMC
    # PROP = Suppress(SkipTo(LineEnd())) + Suppress(SkipTo(LineStart())) + STUFF + Suppress(SkipTo(StringEnd()))  # noqa: E501

    def pprint_assign(var, value, tid="", init=False):
        def fmt(match, store_name, tid):
            tid = match[1] if len(match.groups()) > 1 else tid
            k = match[2] if len(match.groups()) > 1 else match[1]
            agent = f"{pprint_agent(info, tid)}:" if tid != "" else ""
            assign = info.pprint_assign(store_name, int(k), value)
            # endline = " " if not(init) and store_name == "L" else "\n"
            return f"\n{agent}\t{assign}"
        is_attr = ATTR.match(var)
        if is_attr and info.i:
            return fmt(is_attr, "I", tid)
        is_env = ENV.match(var)
        if is_env:
            return fmt(is_env, "E", tid)
        is_lstig = LSTIG.match(var)
        if is_lstig:
            return fmt(is_lstig, "L", tid)
        return ""

    cex_start_pos = cex.find("Counterexample:") + 15
    cex_end_pos = cex.rfind("Violated property:")
    states = parser.parse(cex[cex_start_pos:cex_end_pos]).children

    inits = [
        (s.lhs, s.rhs) for s in states
        if s.function == "init" and not LTSTAMP.match(s.lhs)]
    # Hack to display variables which were initialized to 0
    for (store, loc) in ((info.e, "E"), (info.i, "I"), (info.lstig, "L")):
        for tid in range(info.spawn.num_agents()):
            for var in store.values():
                vals = var.values(tid)
                if len(vals) == 1 and vals[0] == 0:
                    size = var.size if var.is_array else 1
                    for off in range(0, size):
                        tid_fmt = f"[{tid}]" if loc != "E" else ""
                        inits.append((f"{loc}{tid_fmt}[{var.index + off}]", "0"))  # noqa: E501
            if store == info.e:
                break

    others = (
        s for s in states
        if s.function not in ("init", "__CPROVER_initialize"))
    yield "<initialization>"
    for i in inits:
        pprint = pprint_assign(*i, init=True)
        if pprint:
            yield pprint
    yield "\n<end initialization>"

    agent = ""
    system = None
    last_line = None
    for i, state in enumerate(others):
        if state.lhs == "__LABS_step":
            if system:
                yield f"\n<end {system}>"
                system = None
            yield f"""\n<step {state.rhs}>"""
        elif state.lhs == "__sim_spurious" and state.rhs is True:
            yield "\n<spurious>"
            break
        elif state.lhs == "guessedkey":
            system = state.function
            yield f"\n<{pprint_agent(info, agent)}: {state.function} '{info.lstig[int(state.rhs)].name}'>"  # noqa: E501
        elif state.lhs in ("firstAgent", "scheduled"):
            agent = state.rhs
        # simulation: printf messages
        elif state.lhs == "format" and state.rhs.startswith('"(SIMULATION)'):
            yield f"\n<{state.rhs[1:-1]}>"
        # If multiple assignments correspond to the same line, it's because
        # we assigned to an array and CBMC is printing out the whole thing
        elif last_line != state.line:
            pprint = pprint_assign(state.lhs, state.rhs, agent)
            last_line = state.line
            if pprint:
                yield pprint

    violation = cex[cex_end_pos + 18:].splitlines()
    if len(violation) >= 3 and "__sliver_simulation__" not in violation[2]:
        yield f"\n<property violated: '{violation[2].strip()}'>"
    yield "\n"


class Cbmc(Backend):
    def __init__(self, cwd, cli):
        super().__init__(cwd, cli)
        self.name = "cbmc"
        self.modalities = ("always", "finally", "eventually", "between")
        self.language = Language.C

    def get_cbmc_version(self, cmd):
        CBMC_V, *CBMC_SUBV = check_output(
            [cmd[0], "--version"],
            cwd=self.cwd).decode().strip().split(" ")[0].split(".")
        CBMC_SUBV = CBMC_SUBV[0]
        return CBMC_V, CBMC_SUBV

    def get_cmdline(self, fname, _):
        from_environment = os.environ.get("SLIVER_CBMC")
        if from_environment:
            cmd = [from_environment]
        elif "Linux" in platform.system():
            with (
                resources.path("sliver.cbmc", "cbmc-simulator") as cbmc_exec,
                resources.path("sliver.cbmc", "cbmc-5-74") as cbmc_new_exec,
            ):
                cmd = [
                    cbmc_new_exec
                    if self.cli[Args.CONCRETIZATION] == "sat"
                    else cbmc_exec]
        else:
            cmd = ["cbmc"]
        CBMC_V, CBMC_SUBV = self.get_cbmc_version(cmd)
        if not (int(CBMC_V) <= 5 and int(CBMC_SUBV) <= 4):
            cmd += ["--trace", "--stop-on-fail"]
        if (int(CBMC_V) >= 6):
            cmd.append("--no-standard-checks")
        if self.cli[Args.DEBUG]:
            cmd += ["--bounds-check", "--signed-overflow-check"]
        cmd.append(fname)
        return cmd

    def get_dimacs_mapping(self, fname, info):
        """Returns a dictionary from variable names to propositional vars"""
        with tempfile.NamedTemporaryFile() as dimacs_file:
            cmd = self.get_cmdline(fname, info)
            cmd.extend(("--dimacs", "--outfile", dimacs_file.name))
            _ = check_output(cmd, stderr=DEVNULL)
            dimacs_file.seek(0)
            return DimacsMapping(dimacs_file)

    def source_level_concretization(self, fname, info):
        cmd = self.get_cmdline(fname, info)
        c = Concretizer(info, self.cli, True)
        c.concretize_file(fname)
        if self.cli[Args.TIMEOUT] > 0:
            cmd = [self.timeout_cmd, str(self.cli[Args.TIMEOUT]), *cmd]
        log_call(cmd)
        out = check_output(cmd, stderr=STDOUT, cwd=self.cwd).decode()
        self.verbose_output(out, "Backend output")

    def _set_executable(self, filename):
        st = os.stat(filename)
        os.chmod(filename, st.st_mode | stat.S_IEXEC)

    def minisat_incantation(self, weaks, num_vars, script_file):
        with resources.path("sliver.minisat", "minisat") as minisat:
            weaks = " ".join((
                str(var) if value != 0 else f"-{var}"
                for var, value in weaks
                # Skip stuff that has already been resolved by CBMC
                if var not in ("TRUE", "FALSE")
            ))

            seed = self.cli.get_seed()

            if weaks:
                with tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="utf-8") as weaks_f:  # noqa: E501
                    weaks_f.write(weaks)
                    self.temp_files.append(weaks_f.name)
            tryassume = f"""-try-assume-from="{weaks_f.name}" """ if weaks else ""  # noqa: E501
            more_random = "-no-elim -rnd-init " if num_vars < 1_000_000 else ""
            # TODO adjust rnd-freq based on CNF hardness
            freq = (
                "0.15" if num_vars < 1_000_000 else
                "0.05" if num_vars < 3_000_000 else
                "0.01")
            script = f"""
#!/bin/bash

# (c) 2022-2023 Luca Di Stefano, GU, Sweden
# This shell script was automatically generated by SLiVER
# https://github.com/labs-lang/sliver

# Invokes minisat with weak assumptions and nondet heuristics
{minisat} -model -rnd-freq={freq} {more_random} -rnd-seed={seed} {tryassume}$1
"""
            sat_cmd = script.splitlines()[-1].strip()
            self.verbose_output(f"SAT solver call: {sat_cmd}")
            with open(script_file, "w") as f:
                f.write(script)
            self._set_executable(script_file)
            self._set_executable(script_file)

    def sat_level_concretization(self, fname, info, concretizer, script):

        def to_bv(num, width=16):
            """Converts num to a (LSB-first) bitvector of the given width.
            """
            two_compl = num < 0
            if two_compl:
                num = -num
            binary = []
            while num != 0:
                binary.append(num % 2)
                num = num // 2

            # 2's complement if num was negative, otherwise push a 0
            if two_compl:
                found_one = False
                for x in range(len(binary)):
                    if x == 1 and not found_one:
                        found_one = True
                        continue
                    if found_one:
                        binary[x] = 1 if binary[x] == 0 else 0
            else:
                binary.append(0)

            # sign extension
            if width > len(binary):
                binary.extend([binary[-1]] * (width - len(binary)))
            # TODO dail if the width < len(binary)
            return binary

        with open(fname) as file:
            program = file.read()

        m = concretizer.get_concretization(program, return_model=True)
        mapping = self.get_dimacs_mapping(fname, info)
        self.verbose_output(f"DIMACS header: {mapping.info}")

        def bit_train():
            while True:
                yield getrandbits(1)

        nondets = (
            zip(mapping[name], bit_train())
            for name in mapping.mapping
            if "nondetInRange::1::x" in name)
        weaks = [(a, b) for n in nondets for a, b in n]
        for x in m:
            # TODO environment and stigmergy variables
            if str(x).startswith("I_"):
                loc, agent, index = str(x).split("_")
                var = get_var(info.spawn[int(agent)].iface, int(index))
                # Skip if value is already deterministic
                if len(var.values(int(agent))) == 1:
                    continue
                try:
                    dims = (
                        info.spawn.num_agents(),
                        info.max_key_i() + 1)
                    vars_ = mapping.get_element(loc, (int(agent), int(index)), dims)  # noqa: E501
                except KeyError:
                    self.verbose_output(
                        f"Warning: concretization could not find {x}")
                    vars_ = None
            elif str(x).startswith("sched__") and not self.cli[Args.FAIR]:
                _, step = str(x).split("__")
                vars_ = mapping.get_element(
                    "main::1::sched!0@1",
                    (int(step), ),
                    (int(self.cli[Args.STEPS]), ))
            else:
                continue
            if vars_ is not None:
                w = zip(vars_, to_bv(int(m[x].as_string()), len(vars_)))
                weaks.extend(w)
        num_vars = int(mapping.info.split()[2])
        self.minisat_incantation(weaks, num_vars, script)
        return weaks

    def simulate(self, fname, info):
        c = Concretizer(info, self.cli, True)
        from shutil import copyfile
        with tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="utf-8") as orig:  # noqa: E501
            self.temp_files.append(orig.name)
            copyfile(fname, orig.name)
            orig.close()
        exc = ThreadPoolExecutor()
        for i in range(self.cli[Args.SIMULATE]):
            cmd = self.get_cmdline(fname, info)
            try:
                # Concretization step
                if self.cli[Args.CONCRETIZATION] != "none":
                    c.concretize_file(orig.name, dest=fname)
                if self.cli[Args.CONCRETIZATION] == "sat":
                    with (tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="utf-8") as sleepy,  # noqa: E501
                          tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="utf-8") as script):  # noqa: E501
                        self.temp_files.append(sleepy.name)
                        self.temp_files.append(script.name)
                        sleepy.write(
                            "#!/bin/sh\n\n"
                            f"while [ ! -x {script.name} ]; "  # noqa: E501
                            "do sleep 1; done;\n"
                            f"{script.name} $1\n")
                        sleepy.close()
                        self._set_executable(sleepy.name)
                        exc.submit(self.sat_level_concretization, fname, info, c, script.name)  # noqa: E501
                    cmd.extend(["--external-sat-solver", sleepy.name])

                if self.cli[Args.TIMEOUT] > 0:
                    cmd = [self.timeout_cmd, str(self.cli[Args.TIMEOUT]), *cmd]
                log_call(cmd)

                result = run(
                    cmd, cwd=self.cwd, check=True, stderr=PIPE, stdout=PIPE)
                out = result.stdout.decode()
                self.verbose_output(result.stderr.decode(), "Backend stderr")
                self.verbose_output(out, "Backend output")
            except CalledProcessError as err:
                out = err.output.decode("utf-8")
                self.verbose_output(err.stderr.decode(), "Backend stderr")
                self.verbose_output(out, "Backend output")
                try:
                    trace_hash = sha1()
                    header = f"====== Trace #{i+1} ======"
                    print(header)
                    for x in self.translate_cex(out, info):
                        trace_hash.update(x.encode())
                        print(x, sep="", end="")
                    # This just prints a line of '=' that is as long as header
                    print(f'{"" :=<{len(header)}}')
                    self.verbose_output(f"Digest of trace #{i+1}: {trace_hash.hexdigest()}")  # noqa: E501
                except Exception as e:
                    print(f"Counterexample translation failed: {e}")
        return ExitStatus.SUCCESS

    def check_cli(self):
        super().check_cli()
        if not self.cli[Args.STEPS] and not self.cli[Args.SHOW]:
            raise SliverError(
                status=ExitStatus.INVALID_ARGS,
                error_message="Backend 'cbmc' requires --steps N (with N>0)."
            )

    def translate_cex(self, cex, info):
        cmd = self.get_cmdline("", "")
        CBMC_V, CBMC_SUBV = self.get_cbmc_version(cmd)
        if not (int(CBMC_V) <= 5 and int(CBMC_SUBV) <= 4):
            return translateCPROVERNEW(cex, info)
        else:
            return translateCPROVER54(cex, info)

    def handle_error(self, err: CalledProcessError, fname, info):
        if err.returncode == 10:
            out = err.output.decode("utf-8")
            print(*self.translate_cex(out, info), sep="", end="")
            return ExitStatus.FAILED
        elif err.returncode == 6:
            print("Backend failed with parsing error.")
            return ExitStatus.BACKEND_ERROR
        else:
            return super().handle_error(err, fname, info)
