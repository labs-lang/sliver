
            SLiVER  5.1
          6 November 2024

The SLiVER LAbS VERification tool

    * Package contents *


examples/         LAbS example specifications

HISTORY           SLiVER changelog

README.md         General description of SLiVER

README.txt        this file

requirements.txt  Python packages required by SLiVER

sliver.py         SLiVER command-line front-end

sliver/           SLiVER code

(Other files)     Libraries used by SLiVER

    * Installation *

To install SLiVER, please follow the steps below:

    1. install Python 3.10 or higher.
       We recommend setting up a dedicated Python installation/environment
       by using pyenv or similar tools.

    2. create a directory, suppose this is called /workspace

    3. extract the entire package contents in /workspace
    
    4. set execution permissions (chmod +x) for the following files:
        - sliver.py
        - sliver/cbmc/cbmc-simulator
        - sliver/cbmc/cbmc-5-74
        - sliver/minisat/minisat

    5. Install dependencies with (pip install -r requirements.txt)

    6. optionally set execution permissions also for cseq/cseq.py (required to use the cseq backend)

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
