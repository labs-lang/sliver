
              SLiVER 1.6
              February 2021

Symbolic LAbS VERifier

    * Package contents *

README.txt        this file

sliver.py         SLiVER command-line front-end

cex.py            SLiVER counterexample translation module

core/             CSeq core framework

labs/             LAbS parser and translator

examples/         LAbS example specifications

cbmc-simulator    A build of CBMC 5.4

(Other files)     Libraries used by CSeq/SLiVER

    * Installation *

To install SLiVER, please follow the steps below:

    1. install Python 3.5 or higher

    2. create a directory, suppose this is called /workspace

    3. extract the entire package contents in /workspace
    
    4. set execution (+x) permissions for sliver.py and cbmc-simulator

    * Usage *

To try SLiVER, please use the following command:

    ./sliver.py --steps 12 --fair examples/boids-aw.labs birds=3 delta=13 grid=10

which should report that no property is violated.

The following command should instead report that a property is violated:

    ./sliver.py --steps 18 --fair examples/boids-aw.labs birds=4 delta=13 grid=10

Use the --backend=<cbmc|cseq|esbmc> option to select a different
verification backend. 
Please keep in mind that ESBMC support is still experimental, therefore:

  1. The esbmc executable is not provided as part of this package
  2. Our counterexample translation only supports CBMC and CSeq.

Invoking the tool without options:

    ./sliver.py

will provide further usage directions.
