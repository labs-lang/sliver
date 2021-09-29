
# The SLiVER LAbS VERification tool

SLiVER is a tool for the analysis of multi-agent systems specified in the
LAbS language [1]. At the moment, it support under-approximate analysis
via bounded model checking, or analysis of the full state space via
explicit-state model checking.

This page contains source code and binary releases of SLiVER for Linux x64 systems.

## Package contents 

Typically, a SLiVER release will contain the following files and directories:

|Filename|Description
|---------------------|----------------------------------|
|`atlas/`, `cadp/`    |Files used by CADP backends|
|`cbmc-simulator`     |CBMC5.4 binary|
|`cseq/`              |CSeq analysis tool|
|`examples/`          |Example LAbS specifications|
|`labs/`              |LAbS parser and translator|
|`HISTORY`            |Change log|
|`LICENSE`            |The software license for SLiVER|
|`LICENSE_cbmc`       |The software license for CBMC|
|`README.md`          |This document|
|`README.txt`         |Release-specific instructions|
|`sliver.py`          |SLiVER command-line front-end|
|`*.py`               |SLiVER support files| 
|*other files and directories*      |Python libraries used by SLiVER|

## Installation and usage

To install SLiVER, please follow the steps below:

1. install Python 3.8 or higher.
    
2. (Optional) Install Python 2.7 (required by the bundled CSeq backend).

3. Download and extract the latest version of SLiVER from the [**Releases** page](https://github.com/labs-lang/sliver/releases)

4. set execution (+x) permissions for `sliver.py`, `cseq/cseq.py`, `cbmc-simulator` 

5. Invoking `./sliver.py --help` from the command line should now display basic usage directions.

6. Follow `README.txt` for additional (release-specific) instructions.

The COORDINATION paper [3] 
[(PDF)](https://hal.inria.fr/hal-02890401/en)
contains further usage information.

## Support

If you encounter any issues while running SLiVER, please submit
an [issue](https://github.com/labs-lang/sliver/issues).

## Publications

[1] R. De Nicola, L. Di Stefano, and O. Inverso, “Multi-Agent Systems with Virtual Stigmergy,” in Software Technologies: Applications and Foundations (STAF) Workshops. LNCS, vol 11176. Springer, 2018. [Link](https://doi.org/10.1007/978-3-030-04771-9_26)

[2] R. De Nicola, L. Di Stefano, and O. Inverso, “Multi-agent systems with virtual stigmergy,” Sci. Comput. Program., vol. 187, p. 102345, 2020. [Link](https://doi.org/10.1016/j.scico.2019.102345)

[3] L. Di Stefano, F. Lang, and W. Serwe, “Combining SLiVER with CADP to Analyze Multi-agent Systems,” in 22nd International Conference on Coordination Models and Languages (COORDINATION). LNCS, vol. 12134. Springer, 2020. [Link](https://doi.org/10.1007/978-3-030-50029-0_23)

[4] L. Di Stefano, “Modelling and Verification of Multi-Agent Systems via Sequential Emulation,” PhD Thesis, Gran Sasso Science Institute, L’Aquila, Italy, 2020. [Link](https://iris.gssi.it/handle/20.500.12571/10181)

[5] L. Di Stefano and F. Lang, “Verifying temporal properties of stigmergic collective systems using CADP,” in 10th International Symposium On Leveraging Applications of Formal Methods, Verification and Validation (ISoLA), LNCS, vol. 13036. Springer, 2021 (To appear).
