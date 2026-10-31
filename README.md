# University Course Timetable Scheduler

A COMP338 project that builds university course timetables using a genetic algorithm, with a hill-climbing baseline for comparison. Includes a Tkinter desktop interface, a command-line interface, sample datasets, and reproducible experiments.

![Timetable interface](docs/figures/gui_weekly_grid.png)

## Features

- Schedule courses across rooms, days, and periods.
- Evaluate instructor, room, and student-group conflicts, room capacity and type, and instructor availability.
- Optimize preferences, student gaps, and other soft constraints.
- Compare selection, crossover, and mutation operators with configurable parameters and random seeds.
- Export HTML and CSV timetables, JSON results, and convergence data and plots.

## Requirements

Python 3.10 or newer. The scheduler uses the standard library; Matplotlib provides plotting for exports and experiments. The desktop interface requires Tkinter, which is included with many Python installations. On Linux, it may require a separate system package such as `python3-tk`.

```sh
python -m pip install -r requirements.txt
```

Run commands below from this repository's root.

## Run

Open the desktop interface:

```sh
python main.py
```

Generate a timetable in the terminal:

```sh
python main.py --cli --data data/sample_30.json --seed 42
```

Export a run to a new folder:

```sh
python main.py --cli --courses 20 --save results/my_run
```

Compare with hill climbing:

```sh
python main.py --cli --courses 20 --algorithm hill
```

See all options with `python main.py --help`.

## Tests and experiments

Run the existing unit tests:

```sh
python -m unittest -v
```

Run a short experiment pipeline into a separate folder:

```sh
python experiments.py --quick --output results/quick_run
```

The full study uses ten seeds and 500 generations by default. Save new runs separately to preserve the included results:

```sh
python experiments.py --output results/full_run
```

## Included material

- `main.py`: scheduling algorithms, evaluation, interface, and exports.
- `experiments.py`: parameter studies and algorithm comparisons.
- `test_project.py`: regression tests.
- `data/`: sample datasets containing 10 to 50 courses.
- `results/demo/`: saved example timetable and convergence outputs.
- [Experimental report](results/experiments/REPORT.md): recorded measurements and figures.
- [Project report](docs/COMP338_Report.pdf): full report; editable Word version is also in `docs/`.

Optimization is stochastic. Seeds make runs reproducible within the same implementation, but the algorithms do not guarantee a globally optimal timetable.
