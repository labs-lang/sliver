#!/usr/bin/env python3
import os
from hashlib import sha1
import platform
from random import getrandbits
import stat
import tempfile
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache, reduce
from importlib import resources
from operator import mul
from subprocess import (DEVNULL, PIPE, STDOUT, CalledProcessError,
                        check_output, run)

from ..app.cex import translateCPROVER54, translateCPROVERNEW
from ..app.cli import Args, ExitStatus, SliverError
from ..app.info import get_var
from ..atlas.concretizer import Concretizer
from .common import Backend, Language, log_call


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
            if weaks:
                with tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="utf-8") as weaks_f:  # noqa: E501
                    weaks_f.write(weaks)
                    self.temp_files.append(weaks_f.name)
            tryassume = f"""-try-assume-from="{weaks_f.name}" """ if weaks else ""  # noqa: E501
            elim = "-no-elim " if num_vars < 2_000_000 else ""
            # TODO adjust rnd-freq based on CNF hardness
            frequency = "-rnd-freq=0.15"
            script = f"""
#!/bin/bash

# (c) 2022-2023 Luca Di Stefano, GU, Sweden
# This shell script was automatically generated by SLiVER
# https://github.com/labs-lang/sliver

# Invokes minisat with weak assumptions and nondet heuristics
{minisat} -model {frequency} {elim}-rnd-init -rnd-seed=$RANDOM {tryassume}$1
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
        cmd = self.get_cmdline(fname, info)
        c = Concretizer(info, self.cli, True)
        for i in range(self.cli[Args.SIMULATE]):
            try:
                # Concretization step
                if self.cli[Args.CONCRETIZATION] != "none":
                    c.concretize_file(fname)
                if self.cli[Args.CONCRETIZATION] == "sat":
                    # exc = ThreadPoolExecutor()
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
                        # exc.submit(self.sat_level_concretization, fname, info, c, script.name)  # noqa: E501
                        self.sat_level_concretization(fname, info, c, script.name)  # noqa: E501

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
