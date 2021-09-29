
              SLiVER 2.0
              October 2021

The SLiVER LAbS VERification tool

    * Package contents *

atlas/, cadp/     Files used by cadp and cadp-monitor backend

cseq/             CSeq analysis tool

examples/         LAbS example specifications

labs/             LAbS parser and translator

cbmc-simulator    A build of CBMC 5.4

HISTORY           SLiVER changelog

README.txt        this file

sliver.py         SLiVER command-line front-end

(Other files)     Libraries used by SLiVER

    * Installation *

To install SLiVER, please follow the steps below:

    1. install Python 3.8 or higher

    2. create a directory, suppose this is called /workspace

    3. extract the entire package contents in /workspace
    
    4. set execution permissions (chmod +x) for sliver.py and cbmc-simulator

    5. optionally set execution permissions also for cseq/cseq.py (required to use the cseq backend)

    * Usage *

To try SLiVER, please use the following command:

    ./sliver.py --steps 12 --fair examples/boids-aw.labs birds=3 delta=13 grid=10

which should report that no property is violated.

The following command should instead report that a property is violated:

    ./sliver.py --steps 18 --fair examples/boids-aw.labs birds=4 delta=13 grid=10

Use the --backend=<cbmc|cseq|esbmc|cadp|cadp-monitor> option to select a different
verification backend. 
Please keep in mind that:

  1. We only bundled the CBMC executable as part of this package. Therefore,
     cadp, cseq, or esbmc must be obtained separately.
  2. Our counterexample translation does not support esbmc yet.


Invoking the tool without options:

    ./sliver.py

will provide further usage directions.

