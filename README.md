
# SLiVER (Symbolic LAbS VERifier)

SLiver is a tool for the analysis of multi-agent systems specified in the
LAbS language [1]. At the moment, it support under-approximate analysis
via bounded model checking.

This page contains source code and binary releases of SLiVER for Linux x64 systems.

## Package contents 

Typically, a SLiVER release will contain the following files and directories:

|Filename|Description
|-------------------|----------------------------------|
|cbmc-simulator     |CBMC5.4 binary|
|cseq/              |CSeq core framework|
|examples/          |Example LAbS specifications|
|HISTORY            |Change log|
|labs/              |LAbS parser and translator|
|LICENSE            |The software license for SLiVER|
|README.txt         |Release-specific instructions|
|sliver.py          |SLiVER command-line front-end|
|*.py               |SLiVER support files| 
|*other files*      |Python libraries used by SLiVER|

## Installation and usage

To install SLiVER, please follow the steps below:

1. install Python 3.5 or higher.
    
2. (Optional) Install Python 2.7 (required by the bundled CSeq backend).

3. Download and extract the latest version of SLiVER from the [**Releases** page](https://github.com/labs-lang/sliver/releases)

4. set execution (+x) permissions for `sliver.py`, `cseq/cseq.py`, `cbmc-simulator` 
5. Invoking `./sliver.py --help` from the command line should now display basig usage directions.

6. Follow `README.txt` for additional (release-specific) instructions.

## Support

If you encounter any issues while running SLiVER, please submit
an [issue](https://github.com/labs-lang/sliver/issues).

## Publications

[1] R. De Nicola, L. Di Stefano, and O. Inverso, “Multi-Agent Systems with Virtual Stigmergy,” in: Mazzara M., Ober I., Salaün G. (eds) Software Technologies: Applications and Foundations. STAF 2018. Lecture Notes in Computer Science, vol 11176. Springer, 2018. [Link](https://link.springer.com/chapter/10.1007%2F978-3-030-04771-9_26)
