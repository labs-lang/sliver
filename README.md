
# SLiVER (Symbolic LAbS VERifier)

SLiver is a tool for the analysis of multi-agent systems specified in the
LAbS language [1]. At the moment, it support under-approximate analysis
via bounded model checking.

This page contains binary releases of SLiVER for Linux x64 systems.

## Package contents 

Typically, a SLiVER release will contain the following files and directories:

|Filename|Description
|------------------|----------------------------------|
|README.txt        |Installation instructions
|sliver.py         |SLiVER command-line front-end|
|core/             |CSeq core framework|
|labs/             |LAbS parser and translator|
|lib/              |Frontend libraries|
|*.labs            |Example LAbS specifications|
|cbmc-simulator    |CBMC5.4 binary|
|*other files*     |CSeq and Python libraries used by SLiVER|

## Installation

To install SLiVER, please follow the steps below:

1. install Python 3.5 or higher.
    
2. (Optional) Install Python 2.7 with the `pycparser` module
   (required by the bundled CSeq backend).

2. create a directory, suppose this is called `/workspace`

3. Download the latest version of SLiVER from the [**Releases** page](https://github.com/lou1306/sliver/releases)

4. extract the entire package contents in `/workspace`

5. set execution (+x) permissions for `sliver.py`, `cseq.py`, `cbmc-simulator` 

6. make sure that the backend's binary is in the search path, or
   amend the command strings in `sliver.py` accordingly.

7. Follow `/workspace/README.txt` for additional instructions.

## Usage

All releases contain one or more examples. Please follow the README.txt file for specific instructions on how to analyse them.

Invoking the tool with the `--help` switch:

    ./sliver.py --help

will provide further usage directions.

## Support

If you encounter any issues while running SLiVER, please submit
an [issue](https://github.com/lou1306/sliver/issues).

## Publications

[1] R. De Nicola, L. Di Stefano, and O. Inverso, “Multi-Agent Systems with Virtual Stigmergy,” in: Mazzara M., Ober I., Salaün G. (eds) Software Technologies: Applications and Foundations. STAF 2018. Lecture Notes in Computer Science, vol 11176. Springer, 2018. [Link](https://link.springer.com/chapter/10.1007%2F978-3-030-04771-9_26)
