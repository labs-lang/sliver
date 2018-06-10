
# SLiVER 1.0 • May 2018

Symbolic LAbS VERifier

## Package contents 

|Filename|Description
|------------------|----------------------------------|
|README.txt        |this file|
|sliver.py         |SLiVER command-line front-end|
|core/             |CSeq core framework|
|labs/             |LAbS parser and translator|
|lib/              |Frontend libraries|
|flock.labs        |a simple, parametric LAbS system|
|*other files*     |CSeq|


## Installation

To install SLiVER, please follow the steps below:

1. install the dependencies:
    - Python 3.5 or higher
    - backends: CBMC, ESBMC, CSeq
      (none of the above tools is specifically required
      but at least one of them is needed for verification).
    
   The bundled CSeq backend requires Python 2.7 with the `pycparser` module.

2. create a directory, suppose this is called `/workspace`

3. extract the entire package contents in `/workspace`

4. set execution (+x) permissions for `sliver.py`

5. make sure that the backend's binary is in the search path, or
   amend the command strings in `sliver.py` accordingly.


## Usage

To try SLiVER, please use the following command:

    ./sliver.py --steps 12 --fair flock.labs birds=3 delta=22 grid=16

which should report that no property is violated.

The following command should instead report that a property is violated:

    ./sliver.py --steps 12 --fair flock.labs birds=3 delta=21 grid=16

Invoking the tool with the `--help` switch:

    ./sliver.py --help

will provide further usage directions.
