import argparse
import csv
import json
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from html import escape
from itertools import accumulate
from math import ceil, isfinite
from pathlib import Path
from queue import Queue, Empty
from random import Random
from threading import Thread
from time import process_time

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
except ImportError:
    tk = None


@dataclass(frozen=True)
class Room:
    id: str
    capacity: int
    type: str


@dataclass(frozen=True)
class Instructor:
    id: str
    name: str
    unavailable: tuple[tuple[int, int], ...] = ()
    preferred_periods: tuple[int, ...] = ()


@dataclass(frozen=True)
class Course:
    id: str
    name: str
    students: int
    instructor: str
    type: str
    groups: tuple[str, ...]


@dataclass(frozen=True)
class Problem:
    days: tuple[str, ...]
    periods: tuple[str, ...]
    rooms: tuple[Room, ...]
    instructors: tuple[Instructor, ...]
    courses: tuple[Course, ...]

    @property
    def groups(self):
        return sorted({g for c in self.courses for g in c.groups})

    def validate(self):
        for name, values in (("days", self.days), ("periods", self.periods),
                             ("rooms", [x.id for x in self.rooms]),
                             ("instructors", [x.id for x in self.instructors]),
                             ("courses", [x.id for x in self.courses])):
            if not values or len(values) != len(set(values)):
                raise ValueError(f"{name} must be nonempty and unique")
        instructors = {i.id for i in self.instructors}
        for room in self.rooms:
            if room.capacity <= 0 or not room.type:
                raise ValueError("Rooms require positive capacity and a type")
        for i in self.instructors:
            if any(not (0 <= d < len(self.days) and 0 <= t < len(self.periods))
                   for d, t in i.unavailable):
                raise ValueError(f"Invalid unavailable slot for {i.id}")
            if any(not 0 <= t < len(self.periods) for t in i.preferred_periods):
                raise ValueError(f"Invalid preferred period for {i.id}")
        for c in self.courses:
            if c.instructor not in instructors or c.students <= 0:
                raise ValueError(f"Invalid instructor or student count for {c.id}")
            if not c.groups or len(c.groups) != len(set(c.groups)):
                raise ValueError(f"{c.id} needs distinct student groups")
            if not any(r.capacity >= c.students and r.type == c.type for r in self.rooms):
                raise ValueError(f"No suitable room for {c.id}")
        return self

    def slot_number(self, gene):
        d, t, r = gene
        return (d * len(self.periods) + t) * len(self.rooms) + r

    def describe(self, gene):
        d, t, r = gene
        return f"{self.days[d]} {self.periods[t].split('-')[0]} {self.rooms[r].id}"


def from_dict(data):
    return Problem(tuple(data["days"]), tuple(data["periods"]),
                   tuple(Room(**r) for r in data["rooms"]),
                   tuple(Instructor(i["id"], i["name"],
                                    tuple(tuple(s) for s in i.get("unavailable", [])),
                                    tuple(i.get("preferred_periods", [])))
                         for i in data["instructors"]),
                   tuple(Course(**{**c, "groups": tuple(c["groups"])})
                         for c in data["courses"])).validate()


def load_problem(path):
    return from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def save_problem(problem, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(problem), indent=2), encoding="utf-8")


DAYS = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday")
PERIODS = ("08:00-09:00", "09:00-10:00", "10:00-11:00", "11:00-12:00")
ROOMS = (Room("R101", 50, "Lecture"), Room("R102", 40, "Lecture"), Room("R103", 35, "Lecture"),
         Room("R104", 25, "Lecture"), Room("LAB1", 30, "Lab"), Room("LAB2", 25, "Lab"))

INSTRUCTORS = (
    ("I01", "Dr. Ahmad", ((1, 2),), (0, 1)),
    ("I02", "Dr. Ali", ((0, 0), (0, 1)), ()),
    ("I03", "Dr. Omar", ((4, 2), (4, 3)), (1, 2)),
    ("I04", "Dr. Lina", ((2, 0),), (2, 3)),
    ("I05", "Dr. Sara", ((3, 1), (3, 2)), (0, 1)),
    ("I06", "Dr. Khaled", ((1, 0), (1, 1)), ()),
    ("I07", "Dr. Rana", ((0, 3),), (1, 2)),
    ("I08", "Dr. Yousef", ((2, 2), (2, 3)), (2, 3)),
    ("I09", "Dr. Nour", ((4, 0), (4, 1)), (1, 2)),
    ("I10", "Dr. Hani", ((3, 3),), ()),
    ("I11", "Dr. Maha", ((0, 2), (1, 2)), (0, 1)),
    ("I12", "Dr. Samer", ((2, 1),), (1, 2)),
    ("I13", "Dr. Dina", ((3, 0), (4, 0)), (2, 3)),
    ("I14", "Dr. Fadi", ((1, 3), (2, 3)), ()),
    ("I15", "Dr. Reem", ((0, 1), (2, 1)), (1, 2)),
    ("I16", "Dr. Tariq", ((4, 3),), (0, 1)),
    ("I17", "Dr. Huda", ((1, 1), (3, 1)), ()),
    ("I18", "Dr. Bassam", ((0, 0), (2, 0), (4, 0)), (1, 2)),
    ("I19", "Dr. Leen", ((3, 2),), (2, 3)),
    ("I20", "Dr. Majd", ((1, 0),), (1, 2)),
)

CATALOGUE = (
    ("Artificial Intelligence", 35, "I01", "Lecture"), ("Database", 40, "I02", "Lecture"),
    ("Networks", 30, "I03", "Lecture"), ("Operating Systems", 35, "I01", "Lecture"),
    ("Software Engineering", 45, "I04", "Lecture"), ("Algorithms", 40, "I05", "Lecture"),
    ("Data Mining", 25, "I06", "Lecture"), ("Computer Graphics", 30, "I07", "Lab"),
    ("Web Programming", 25, "I08", "Lab"), ("Machine Learning", 35, "I06", "Lecture"),
    ("Programming I", 45, "I09", "Lecture"), ("Programming I Lab", 25, "I09", "Lab"),
    ("Discrete Mathematics", 40, "I10", "Lecture"), ("Calculus for Computing", 45, "I11", "Lecture"),
    ("Digital Logic Design", 35, "I12", "Lecture"), ("Programming II", 40, "I02", "Lecture"),
    ("Data Structures", 40, "I05", "Lecture"), ("Data Structures Lab", 25, "I10", "Lab"),
    ("Computer Architecture", 35, "I12", "Lecture"), ("Linear Algebra", 35, "I11", "Lecture"),
    ("Theory of Computation", 30, "I13", "Lecture"), ("Compilers", 30, "I13", "Lecture"),
    ("Computer Security", 35, "I14", "Lecture"), ("Networks Lab", 25, "I03", "Lab"),
    ("Database Lab", 25, "I08", "Lab"), ("Human-Computer Interaction", 30, "I04", "Lecture"),
    ("Probability and Statistics", 45, "I15", "Lecture"), ("Numerical Methods", 30, "I15", "Lecture"),
    ("Mobile Application Development", 25, "I07", "Lab"), ("Cloud Computing", 30, "I14", "Lecture"),
    ("Distributed Systems", 30, "I16", "Lecture"), ("Computer Vision", 25, "I17", "Lecture"),
    ("Natural Language Processing", 25, "I17", "Lecture"), ("Parallel Computing", 25, "I16", "Lecture"),
    ("Information Retrieval", 25, "I06", "Lecture"), ("Embedded Systems Lab", 25, "I18", "Lab"),
    ("Software Testing", 30, "I04", "Lecture"), ("Operating Systems Lab", 25, "I18", "Lab"),
    ("Cyber Security Lab", 25, "I14", "Lab"), ("Deep Learning", 30, "I01", "Lecture"),
    ("Game Development", 25, "I07", "Lab"), ("Big Data Analytics", 30, "I19", "Lecture"),
    ("Network Security", 30, "I03", "Lecture"), ("Robotics", 25, "I20", "Lecture"),
    ("Computer Ethics", 45, "I19", "Lecture"), ("Project Management", 40, "I20", "Lecture"),
    ("Graduation Project I", 35, "I05", "Lecture"), ("Internet of Things", 25, "I12", "Lab"),
    ("Bioinformatics", 25, "I10", "Lecture"), ("Graduation Project II", 35, "I02", "Lecture"),
)

GROUPS = {
    "CS-Y3": (1, 2, 4, 5, 6), "CS-Y4": (3, 5, 7, 8, 10), "CE-Y3": (2, 3, 6, 9),
    "CS-Y1": (11, 12, 13, 14, 15), "CS-Y2": (16, 17, 18, 19, 20), "CE-Y2": (15, 16, 19, 20),
    "CS-Y3B": (21, 22, 23, 25, 27), "SE-Y3": (24, 26, 27, 28, 29, 30),
    "AI-Y4": (10, 32, 33, 35, 40), "CS-Y4B": (31, 34, 36, 37, 38), "CE-Y4": (30, 31, 36, 39),
    "SE-Y4": (37, 41, 45, 46, 47), "DS-Y4": (40, 42, 44, 48, 49), "CY-Y4": (23, 43, 45, 50),
}


def example_problem(size=10):
    if not 1 <= size <= len(CATALOGUE):
        raise ValueError(f"Example size must be between 1 and {len(CATALOGUE)}")
    courses = tuple(Course(f"C{n:02}", name, students, instructor, kind,
                           tuple(g for g, rows in GROUPS.items() if n in rows))
                    for n, (name, students, instructor, kind) in enumerate(CATALOGUE[:size], start=1))
    used = {c.instructor for c in courses}
    instructors = tuple(Instructor(*row) for row in INSTRUCTORS if row[0] in used)
    return Problem(DAYS, PERIODS, ROOMS, instructors, courses).validate()


Gene = tuple[int, int, int]
Chromosome = tuple[Gene, ...]


@dataclass(frozen=True)
class Score:
    hard: int
    soft: int
    penalty: int
    fitness: float
    hard_details: dict
    soft_details: dict


class Evaluator:
    HARD = ("instructor_conflict", "room_conflict", "student_conflict",
            "room_capacity", "room_type", "instructor_availability")
    SOFT = ("early_classes", "late_classes", "student_gaps",
            "instructor_preferences", "group_working_days")

    def __init__(self, problem, restricted=True):
        self.problem = p = problem.validate()
        self.instructors = {i.id: i for i in p.instructors}
        D, T, R = len(p.days), len(p.periods), len(p.rooms)
        self.shape = (D, T, R)
        self.soft_weight = 10
        bound = 3 * len(p.courses) + len(p.groups) * (D * max(0, T - 2) + D - 1)
        self.hard_weight = max(100, (bound + 1) * self.soft_weight)
        teacher_index = {i.id: k for k, i in enumerate(p.instructors)}
        group_index = {g: k for k, g in enumerate(p.groups)}
        self._teacher = [teacher_index[c.instructor] for c in p.courses]
        self._groups = [tuple(group_index[g] for g in c.groups) for c in p.courses]
        self._students = [c.students for c in p.courses]
        self._type = [c.type for c in p.courses]
        self._capacity = [r.capacity for r in p.rooms]
        self._room_type = [r.type for r in p.rooms]
        self._blocked = [frozenset(d * T + t for d, t in self.instructors[c.instructor].unavailable)
                         for c in p.courses]
        self._preferred = [frozenset(self.instructors[c.instructor].preferred_periods) for c in p.courses]
        self._gaps = [0] + [m.bit_length() - (m & -m).bit_length() + 1 - bin(m).count("1")
                            for m in range(1, 1 << T)]
        grid = tuple((d, t, r) for d in range(D) for t in range(T) for r in range(R))
        self.domains = []
        for i, c in enumerate(p.courses):
            valid = tuple(g for g in grid if self.unary_ok(i, g))
            if not valid:
                raise ValueError(f"No available assignment for {c.id}")
            self.domains.append(valid if restricted else grid)
        self.domain_sets = [frozenset(domain) for domain in self.domains]
        self.by_room, self.by_time = [], []
        for domain in self.domains:
            rooms, times = defaultdict(list), defaultdict(list)
            for gene in domain:
                rooms[gene[2]].append(gene)
                times[gene[:2]].append(gene)
            self.by_room.append({k: tuple(v) for k, v in rooms.items()})
            self.by_time.append({k: tuple(v) for k, v in times.items()})

    def unary_ok(self, i, gene):
        d, t, r = gene
        return (self._students[i] <= self._capacity[r] and self._type[i] == self._room_type[r]
                and d * self.shape[1] + t not in self._blocked[i])

    def evaluate(self, chromosome):
        D, T, R = self.shape
        S, n_groups = D * T, len(self.problem.groups)
        if len(chromosome) != len(self._teacher):
            raise ValueError("One gene is required for every course")
        teacher_use = [0] * (len(self.problem.instructors) * S)
        room_use = [0] * (R * S)
        group_use = [0] * (n_groups * S)
        day_mask = [0] * (n_groups * D)
        ic = rc = sc = cap = typ = avail = early = late = pref = 0
        for i, (d, t, r) in enumerate(chromosome):
            if not (0 <= d < D and 0 <= t < T and 0 <= r < R):
                raise ValueError("Gene index outside the scheduling grid")
            slot = d * T + t
            k = self._teacher[i] * S + slot
            ic += teacher_use[k]
            teacher_use[k] += 1
            k = r * S + slot
            rc += room_use[k]
            room_use[k] += 1
            for g in self._groups[i]:
                k = g * S + slot
                sc += group_use[k]
                group_use[k] += 1
                day_mask[g * D + d] |= 1 << t
            cap += self._students[i] > self._capacity[r]
            typ += self._type[i] != self._room_type[r]
            avail += slot in self._blocked[i]
            early += t == 0
            late += t == T - 1
            preferred = self._preferred[i]
            pref += bool(preferred) and t not in preferred
        gaps = extra_days = 0
        for g in range(n_groups):
            used = [m for m in day_mask[g * D:(g + 1) * D] if m]
            extra_days += max(0, len(used) - 1)
            gaps += sum(self._gaps[m] for m in used)
        hard = dict(zip(self.HARD, (ic, rc, sc, cap, typ, avail)))
        soft = dict(zip(self.SOFT, (early, late, gaps, pref, extra_days)))
        h, s = sum(hard.values()), sum(soft.values())
        penalty = self.hard_weight * h + self.soft_weight * s
        return Score(h, s, penalty, 1 / (1 + penalty), hard, soft)


def conflicted_courses(problem, chromosome):
    instructors = {i.id: i for i in problem.instructors}
    users, bad = defaultdict(list), set()
    for i, (c, (d, t, r)) in enumerate(zip(problem.courses, chromosome)):
        for key in (("instructor", c.instructor), ("room", r), *(("group", g) for g in c.groups)):
            users[key + (d, t)].append(i)
        room = problem.rooms[r]
        if room.capacity < c.students or room.type != c.type or (d, t) in instructors[c.instructor].unavailable:
            bad.add(i)
    for members in users.values():
        if len(members) > 1:
            bad.update(members)
    return bad


def initialize_population(evaluator, size, rng):
    return [tuple(rng.choice(domain) for domain in evaluator.domains) for _ in range(size)]


def tournament_selection(population, scores, rng, size=4):
    best = rng.randrange(len(population))
    for _ in range(size - 1):
        i = rng.randrange(len(population))
        if scores[i].penalty < scores[best].penalty:
            best = i
    return population[best]


def roulette_wheel_selection(population, scores, rng, wheel=None):
    wheel = wheel or list(accumulate(s.fitness for s in scores))
    return population[min(bisect_right(wheel, rng.random() * wheel[-1]), len(population) - 1)]


def one_point_crossover(a, b, probability, rng):
    if len(a) < 2 or rng.random() >= probability:
        return a, b
    cut = rng.randrange(1, len(a))
    return a[:cut] + b[cut:], b[:cut] + a[cut:]


def two_point_crossover(a, b, probability, rng):
    if len(a) < 3:
        return one_point_crossover(a, b, probability, rng)
    if rng.random() >= probability:
        return a, b
    left, right = sorted(rng.sample(range(1, len(a)), 2))
    return a[:left] + b[left:right] + a[right:], b[:left] + a[left:right] + b[right:]


def random_mutation(chromosome, evaluator, probability, rng):
    child = list(chromosome)
    for i in range(len(child)):
        if rng.random() < probability:
            child[i] = rng.choice(evaluator.domains[i])
    return tuple(child)


def change_time_mutation(chromosome, evaluator, probability, rng):
    child = list(chromosome)
    for i, gene in enumerate(child):
        if rng.random() < probability:
            child[i] = rng.choice(evaluator.by_room[i].get(gene[2]) or evaluator.domains[i])
    return tuple(child)


def change_room_mutation(chromosome, evaluator, probability, rng):
    child = list(chromosome)
    for i, gene in enumerate(child):
        if rng.random() < probability:
            child[i] = rng.choice(evaluator.by_time[i].get(gene[:2]) or evaluator.domains[i])
    return tuple(child)


def swap_mutation(chromosome, evaluator, probability, rng):
    child = list(chromosome)
    n = len(child)
    for i in range(n if n > 1 else 0):
        if rng.random() < probability:
            j = rng.randrange(n - 1)
            j += j >= i
            a, b = child[i], child[j]
            for new_a, new_b in ((b, a), ((b[0], b[1], a[2]), (a[0], a[1], b[2]))):
                if new_a in evaluator.domain_sets[i] and new_b in evaluator.domain_sets[j]:
                    child[i], child[j] = new_a, new_b
                    break
    return tuple(child)


SELECTIONS = {"tournament": ("Tournament", tournament_selection),
              "roulette": ("Roulette wheel", roulette_wheel_selection)}
CROSSOVERS = {"two_point": ("Two-point", two_point_crossover),
              "one_point": ("One-point", one_point_crossover)}
MUTATIONS = {"random": ("Random reassignment", random_mutation),
             "swap": ("Swap two courses", swap_mutation),
             "time": ("Change time", change_time_mutation),
             "room": ("Change room", change_room_mutation)}


def option_key(options, label):
    return next(key for key, (text, _) in options.items() if text == label)


def diversity(population):
    size = len(population)
    return sum(1 - max(Counter(column).values()) / size for column in zip(*population)) / len(population[0])


@dataclass(frozen=True)
class Config:
    population: int = 100
    generations: int = 500
    mutation: float = 0.05
    crossover: float = 0.8
    elite_fraction: float = 0.05
    tournament: int = 4
    patience: int = 50
    target_soft: int = -1
    seed: int = 42
    selection: str = "tournament"
    crossover_type: str = "two_point"
    mutation_type: str = "random"
    restricted: bool = True

    def validate(self):
        if self.population < 2 or self.generations < 0 or self.tournament < 1 or self.patience < 0:
            raise ValueError("Invalid population, generations, tournament, or patience")
        for name in ("mutation", "crossover", "elite_fraction"):
            value = getattr(self, name)
            if not isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be a finite probability in [0, 1]")
        if self.elite_fraction == 1:
            raise ValueError("Elitism must leave space for offspring")
        for name, options in (("selection", SELECTIONS), ("crossover_type", CROSSOVERS),
                              ("mutation_type", MUTATIONS)):
            if getattr(self, name) not in options:
                raise ValueError(f"Unknown {name}; choose one of {', '.join(options)}")
        return self


@dataclass
class Result:
    chromosome: tuple
    score: object
    history: list
    generations: int
    evaluations: int
    runtime: float
    reason: str
    algorithm: str
    config: dict


def genetic_algorithm(problem, config=Config(), progress=None):
    config.validate()
    start = process_time()
    rng, evaluator = Random(config.seed), Evaluator(problem, config.restricted)
    crossover, mutate = CROSSOVERS[config.crossover_type][1], MUTATIONS[config.mutation_type][1]
    population = initialize_population(evaluator, config.population, rng)
    evaluations = 0
    best, best_score, stalled = None, None, 0
    history, reason = [], "maximum generations"
    elite_count = min(config.population - 1, ceil(config.elite_fraction * config.population))
    for generation in range(config.generations + 1):
        scores = [evaluator.evaluate(c) for c in population]
        evaluations += len(scores)
        rank = sorted(range(len(population)), key=lambda i: scores[i].penalty)
        current = rank[0]
        if best_score is None or scores[current].penalty < best_score.penalty:
            best, best_score, stalled = population[current], scores[current], 0
        else:
            stalled += 1
        history.append({"generation": generation, "fitness": best_score.fitness,
                        "penalty": best_score.penalty, "hard": best_score.hard,
                        "soft": best_score.soft, "evaluations": evaluations,
                        "mean_fitness": sum(s.fitness for s in scores) / len(scores),
                        "diversity": diversity(population)})
        if progress:
            progress(generation, best_score)
        if best_score.hard == 0 and 0 <= best_score.soft <= config.target_soft:
            reason = "target soft score"
            break
        if config.patience and stalled >= config.patience:
            reason = "no improvement"
            break
        if generation == config.generations:
            break
        children = [population[i] for i in rank[:elite_count]]
        if config.selection == "roulette":
            wheel = list(accumulate(s.fitness for s in scores))
            select = lambda: roulette_wheel_selection(population, scores, rng, wheel)
        else:
            select = lambda: tournament_selection(population, scores, rng, config.tournament)
        while len(children) < config.population:
            for child in crossover(select(), select(), config.crossover, rng):
                if len(children) < config.population:
                    children.append(mutate(child, evaluator, config.mutation, rng))
        population = children
    return Result(best, best_score, history, generation, evaluations, process_time() - start,
                  reason, "Genetic Algorithm", asdict(config))


def hill_climbing(problem, iterations=5000, seed=42, record_every=1):
    if iterations < 0 or record_every < 1:
        raise ValueError("Iterations cannot be negative and record_every must be positive")
    start = process_time()
    rng, evaluator = Random(seed), Evaluator(problem)
    current = initialize_population(evaluator, 1, rng)[0]
    score = evaluator.evaluate(current)

    def entry(step):
        return {"generation": step, "fitness": score.fitness, "penalty": score.penalty,
                "hard": score.hard, "soft": score.soft, "evaluations": step + 1}
    history = [entry(0)]
    for step in range(1, iterations + 1):
        neighbor = list(current)
        i = rng.randrange(len(neighbor))
        neighbor[i] = rng.choice(evaluator.domains[i])
        candidate = tuple(neighbor)
        candidate_score = evaluator.evaluate(candidate)
        if candidate_score.penalty <= score.penalty:
            current, score = candidate, candidate_score
        if (step + 1) % record_every == 0 or step == iterations:
            history.append(entry(step))
    return Result(current, score, history, iterations, iterations + 1, process_time() - start,
                  "evaluation budget", "Hill Climbing",
                  {"seed": seed, "iterations": iterations, "record_every": record_every})


def first_generation(history, condition):
    return next((h["generation"] for h in history if condition(h)), None)


def write_csv(path, rows):
    rows = list(rows)
    if not rows:
        return
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def timetable_rows(problem, chromosome):
    instructors = {i.id: i.name for i in problem.instructors}
    return [(problem.days[d], problem.periods[t], c.id, c.name, instructors[c.instructor],
             problem.rooms[r].id, ', '.join(c.groups))
            for c, (d, t, r) in sorted(zip(problem.courses, chromosome), key=lambda pair: pair[1])]


def summary_items(problem, result):
    s = result.score
    placed = len(problem.courses) - len(conflicted_courses(problem, result.chromosome))
    unit = "Generations" if result.algorithm == "Genetic Algorithm" else "Iterations"
    return [("Algorithm", result.algorithm), ("Courses scheduled", f"{placed}/{len(problem.courses)}"),
            ("Hard violations", s.hard), ("Soft violations", s.soft), ("Final penalty", s.penalty),
            ("Best fitness", f"{s.fitness:.5f}"), (unit, result.generations),
            ("Runtime", f"{result.runtime:.2f} s"), ("Stopped by", result.reason)]


def print_report(problem, result, write=print):
    rows = timetable_rows(problem, result.chromosome)
    header = ("Day", "Time", "ID", "Course", "Instructor", "Room", "Groups")
    widths = [max(len(str(v)) for v in column) for column in zip(header, *rows)]

    def line(values):
        return "  ".join(str(v).ljust(w) for v, w in zip(values, widths)).rstrip()
    write(line(header))
    write(line("-" * w for w in widths))
    for row in rows:
        write(line(row))
    write("")
    for label, value in summary_items(problem, result):
        write(f"{label + ':':<19}{value}")
    s = result.score
    write("Hard breakdown:    " + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in s.hard_details.items()))
    write("Soft breakdown:    " + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in s.soft_details.items()))
    write(f"Penalty formula:   {Evaluator(problem).hard_weight} x {s.hard} + 10 x {s.soft} = {s.penalty}")
    write("Chromosome (slot numbers): " + str([problem.slot_number(g) for g in result.chromosome]))


def sample_points(history, limit=600):
    step = max(1, len(history) // limit)
    return history[::step] + ([history[-1]] if (len(history) - 1) % step else [])


def timetable_html(problem, result):
    s = result.score
    instructors = {i.id: i.name for i in problem.instructors}
    bad = conflicted_courses(problem, result.chromosome)
    valid = "Feasible timetable" if s.hard == 0 else "Conflicts remain - review required"
    cards = "".join(f'<div class="card"><span>{escape(label)}</span><strong>{escape(str(value))}</strong></div>'
                    for label, value in summary_items(problem, result)[1:8])
    table = '<tr><th>Period</th>' + ''.join(f'<th>{escape(d)}</th>' for d in problem.days) + '</tr>'
    for t, period in enumerate(problem.periods):
        table += f'<tr><th>{escape(period)}</th>'
        for d in range(len(problem.days)):
            cell = []
            for i, (course, (day, time, room)) in enumerate(zip(problem.courses, result.chromosome)):
                if (day, time) == (d, t):
                    cell.append(f'<article class="{"bad" if i in bad else ""}"><b>{escape(course.name)}</b><small>'
                                + escape(f'{course.id} | {problem.rooms[room].id} | {instructors[course.instructor]}')
                                + '</small><small>' + escape(', '.join(course.groups)) + '</small></article>')
            table += '<td>' + ''.join(cell) + '</td>'
        table += '</tr>'
    details = ''.join(f'<li>{kind}: {escape(k.replace("_", " "))} <b>{v}</b></li>'
                      for kind, items in (("Hard", s.hard_details), ("Soft", s.soft_details))
                      for k, v in items.items())
    points = sample_points(result.history)
    last, top = max(1, points[-1]["generation"]), max(h["fitness"] for h in points)
    line = ' '.join(f'{50 + 880 * h["generation"] / last:.1f},{210 - 170 * h["fitness"] / top:.1f}' for h in points)
    unit = "Generation" if result.algorithm == "Genetic Algorithm" else "Iteration"
    return f'''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>University timetable</title>
<style>body{{font:15px system-ui;margin:32px;background:#f4f6fa;color:#172a42}}main{{max-width:1400px;margin:auto}}
h1{{font-size:32px}}.cards{{display:flex;gap:12px;flex-wrap:wrap}}.card{{background:white;padding:14px 20px;border-radius:10px}}
.card span,small{{display:block;color:#526478}}strong{{display:block;font-size:24px}}table{{width:100%;border-collapse:collapse;background:white;table-layout:fixed}}
th,td{{padding:10px;border:1px solid #dce3ed;vertical-align:top}}th{{background:#eaf0f7}}article{{background:#eef5ff;border-left:3px solid #2869b1;padding:8px 10px;margin-bottom:8px;border-radius:4px}}
article.bad{{background:#fdecea;border-color:#b3261e}}svg{{background:white;width:100%;max-height:260px}}ul{{columns:2}}.scroll{{overflow-x:auto}}
@media(max-width:750px){{body{{margin:12px}}table{{min-width:900px}}ul{{columns:1}}}}</style>
<main><p>COMP338 / ARTIFICIAL INTELLIGENCE</p><h1>Weekly university timetable</h1>
<p>{valid} · {escape(result.algorithm)} · Seed {result.config['seed']} · Stopped by {escape(result.reason)}</p><div class="cards">{cards}</div>
<h2>{escape(problem.days[0])}–{escape(problem.days[-1])}</h2><div class="scroll"><table>{table}</table></div>
<h2>Best fitness convergence</h2><svg viewBox="0 0 960 250" role="img" aria-label="Best fitness over search steps">
<path d="M50 25 V210 H930" fill="none" stroke="#8090a0"/><polyline points="{line}" fill="none" stroke="#2869b1" stroke-width="3"/>
<text x="50" y="20">Best fitness (top: {top:.6f})</text><text x="50" y="235">0</text>
<text x="640" y="235">{unit}: {result.generations}</text></svg>
<h2>Constraint breakdown</h2><ul>{details}</ul><p>Penalty: {s.penalty} · Evaluations: {result.evaluations}</p>
<p>One one-hour meeting per course. Several cards in a cell are simultaneous classes in different rooms; red cards are involved in a hard violation.</p></main></html>'''


def export_result(problem, result, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    fields = ("day", "time", "course_id", "course", "instructor", "room", "groups")
    write_csv(directory / "timetable.csv", [dict(zip(fields, row)) for row in timetable_rows(problem, result.chromosome)])
    write_csv(directory / "convergence.csv", result.history)
    (directory / "result.json").write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")
    (directory / "timetable.html").write_text(timetable_html(problem, result), encoding="utf-8")


def plot_convergence(result, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    history = result.history
    ga = result.algorithm == "Genetic Algorithm"
    ink, muted, grid, axis, surface = "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Segoe UI", "DejaVu Sans"]})
    fig, ax = plt.subplots(figsize=(8, 4.5), layout="constrained", facecolor=surface)
    ax.set_facecolor(surface)
    ax.step([h["generation"] for h in history], [h["fitness"] for h in history], where="post",
            color="#2a78d6", linewidth=2, label="Best fitness so far")
    if ga:
        ax.plot([h["generation"] for h in history], [h["mean_fitness"] for h in history],
                color="#eb6834", linewidth=1.2, label="Population mean fitness")
    ax.set_ylim(bottom=0)
    feasible = first_generation(history, lambda h: h["hard"] == 0)
    if feasible is not None:
        ax.axvline(feasible, color=muted, linewidth=1)
        ax.annotate(f"first feasible timetable ({'generation' if ga else 'iteration'} {feasible})",
                    (feasible, ax.get_ylim()[1] * 0.95), xytext=(6, 0), textcoords="offset points",
                    color=ink, fontsize=9, va="top")
    ax.set_xlabel("Generation" if ga else "Iteration", color=ink)
    ax.set_ylabel("Fitness = 1 / (1 + penalty)", color=ink)
    ax.set_title(f"{result.algorithm}: best fitness {result.score.fitness:.5f} "
                 f"(hard {result.score.hard}, soft {result.score.soft})", color="#0b0b0b")
    ax.grid(axis="y", color=grid, linewidth=0.7)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(axis)
    ax.tick_params(colors=axis, labelcolor=ink)
    ax.legend(loc="lower right", frameon=False, labelcolor=ink)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def save_all(problem, result, directory):
    export_result(problem, result, directory)
    save_problem(problem, Path(directory) / "dataset.json")
    try:
        plot_convergence(result, Path(directory) / "convergence.png")
    except ImportError:
        pass


ROOT = Path(__file__).resolve().parent
SAMPLE_NOTE = ('Built-in data: the first 10 courses and 6 rooms come from the brief; larger sizes add '
               'courses, instructors and student groups. Each course meets once per week.')


def parse_settings(values):
    defaults = Config()
    target = str(values.get('target', '')).strip()
    config = Config(population=int(values['population']), generations=int(values['generations']),
                    mutation=float(values['mutation']), crossover=float(values['crossover']),
                    elite_fraction=float(values.get('elite', defaults.elite_fraction)),
                    tournament=int(values.get('tournament', defaults.tournament)),
                    patience=int(values.get('patience', defaults.patience)),
                    target_soft=int(target) if target else -1, seed=int(values['seed']),
                    selection=values.get('selection', defaults.selection),
                    crossover_type=values.get('crossover_type', defaults.crossover_type),
                    mutation_type=values.get('mutation_type', defaults.mutation_type))
    config.validate()
    if config.population > 2000 or config.generations > 10000:
        raise ValueError('For this interface, use at most 2,000 population and 10,000 generations.')
    return config


class SchedulerApp:
    def __init__(self, root):
        self.root = root
        self.problem = self.result = self.custom_path = None
        self.conflicts = set()
        self.queue = Queue()
        self.busy = False
        self.edit_controls = []
        root.title('Course Scheduler - COMP338 Genetic Algorithm')
        root.geometry('1200x820')
        root.minsize(1000, 680)
        style = ttk.Style(root)
        style.configure('.', font=('Segoe UI', 10))
        style.configure('Title.TLabel', font=('Segoe UI', 13, 'bold'))
        style.configure('Muted.TLabel', foreground='#5b6b7d')
        style.configure('Value.TLabel', font=('Segoe UI', 12, 'bold'))
        style.configure('TButton', padding=(8, 4))
        style.configure('Treeview', rowheight=26)
        style.configure('Treeview.Heading', font=('Segoe UI', 10, 'bold'))

        frame = ttk.Frame(root, padding=12)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='University Course Scheduler', style='Title.TLabel').pack(anchor='w', pady=(0, 10))
        settings = ttk.LabelFrame(frame, text='Schedule settings', padding=12)
        settings.pack(fill='x')
        top = ttk.Frame(settings)
        top.grid(row=0, column=0, sticky='w')
        self.dataset = tk.StringVar(value='20 courses')
        self.algorithm = tk.StringVar(value='Genetic Algorithm')
        self.selection = tk.StringVar(value=SELECTIONS['tournament'][0])
        self.crossover_type = tk.StringVar(value=CROSSOVERS['two_point'][0])
        self.mutation_type = tk.StringVar(value=MUTATIONS['random'][0])
        self.combo(top, 'Dataset', self.dataset, [f'{n} courses' for n in (10, 20, 30, 40, 50)], 0, 13,
                   self.select_sample)
        load_button = ttk.Button(top, text='Load JSON...', command=self.load_json)
        load_button.grid(row=1, column=1, padx=(0, 18), sticky='w')
        self.edit_controls.append((load_button, 'normal'))
        self.combo(top, 'Algorithm', self.algorithm, ['Genetic Algorithm', 'Hill Climbing'], 2, 18)
        self.combo(top, 'Selection', self.selection, [v[0] for v in SELECTIONS.values()], 3, 15)
        self.combo(top, 'Crossover', self.crossover_type, [v[0] for v in CROSSOVERS.values()], 4, 11)
        self.combo(top, 'Mutation', self.mutation_type, [v[0] for v in MUTATIONS.values()], 5, 22)
        fields = ttk.Frame(settings)
        fields.grid(row=1, column=0, sticky='w', pady=(12, 0))
        self.values = {}
        for col, (key, label, default) in enumerate([
            ('population', 'Population', '100'), ('generations', 'Max generations', '500'),
            ('mutation', 'Mutation rate', '0.05'), ('crossover', 'Crossover rate', '0.80'),
            ('elite', 'Elitism (0-1)', '0.05'), ('tournament', 'Tournament size', '4'),
            ('patience', 'Patience (gens)', '50'), ('target', 'Target soft', ''),
            ('seed', 'Random seed', '42')]):
            ttk.Label(fields, text=label).grid(row=0, column=col, sticky='w', padx=(0, 12))
            var = tk.StringVar(value=default)
            entry = ttk.Entry(fields, textvariable=var, width=11)
            entry.grid(row=1, column=col, sticky='w', padx=(0, 12), pady=(4, 0))
            self.values[key] = var
            self.edit_controls.append((entry, 'normal'))
        self.data_note = tk.StringVar(value=SAMPLE_NOTE)
        ttk.Label(settings, textvariable=self.data_note, style='Muted.TLabel').grid(row=2, column=0, sticky='w', pady=(10, 0))
        ttk.Label(settings, style='Muted.TLabel', wraplength=1120,
                  text='Mutation rate is per course (gene); crossover rate is per parent pair. Patience 0 never stops early; '
                       'an empty target soft means no target. Hill climbing gets population × (max generations + 1) evaluations.'
                  ).grid(row=3, column=0, sticky='w', pady=(2, 0))
        actions = ttk.Frame(frame)
        actions.pack(fill='x', pady=12)
        self.run_button = ttk.Button(actions, text='Generate timetable', command=self.generate)
        self.run_button.pack(side='left')
        self.save_button = ttk.Button(actions, text='Save results...', command=self.save, state='disabled')
        self.save_button.pack(side='left', padx=8)
        self.progress = ttk.Progressbar(actions, mode='determinate', length=140)
        self.progress.pack(side='right')
        self.status = tk.StringVar(value='Choose your settings, then generate a timetable.')
        ttk.Label(actions, textvariable=self.status).pack(side='left', padx=12)
        summary = ttk.Frame(frame)
        summary.pack(fill='x', pady=(0, 10))
        self.summary = {}
        for col, name in enumerate(('Courses scheduled', 'Hard violations', 'Soft violations', 'Final penalty',
                                    'Best fitness', 'Generations', 'Runtime', 'Stopped by')):
            box = ttk.Frame(summary, padding=(0, 0, 26, 0))
            box.grid(row=0, column=col, sticky='w')
            ttk.Label(box, text=name, style='Muted.TLabel').pack(anchor='w')
            self.summary[name] = tk.StringVar(value='-')
            ttk.Label(box, textvariable=self.summary[name], style='Value.TLabel').pack(anchor='w')

        notebook = ttk.Notebook(frame)
        notebook.pack(fill='both', expand=True)
        schedule, grid, convergence, constraints = (ttk.Frame(notebook, padding=5) for _ in range(4))
        notebook.add(schedule, text='Timetable')
        notebook.add(grid, text='Weekly grid')
        notebook.add(convergence, text='Convergence')
        notebook.add(constraints, text='Constraints')
        self.table = self.make_table(schedule,
            ['Day', 'Time', 'ID', 'Course', 'Instructor', 'Room', 'Groups'],
            [105, 120, 60, 250, 130, 80, 150])
        self.constraints = self.make_table(constraints, ['Type', 'Constraint', 'Violations'], [90, 400, 110])
        self.grid_canvas = tk.Canvas(grid, background='white', highlightthickness=0)
        scroll = ttk.Scrollbar(grid, orient='vertical', command=self.grid_canvas.yview)
        self.grid_canvas.configure(yscrollcommand=scroll.set)
        self.grid_canvas.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.grid_canvas.bind('<Configure>', lambda _: self.draw_grid())
        self.canvas = tk.Canvas(convergence, background='white', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Configure>', lambda _: self.draw_plot())
        root.after(100, self.poll)

    def combo(self, parent, label, variable, values, column, width, command=None):
        ttk.Label(parent, text=label).grid(row=0, column=column, sticky='w')
        box = ttk.Combobox(parent, textvariable=variable, values=values, state='readonly', width=width)
        box.grid(row=1, column=column, sticky='w', padx=(0, 14))
        if command:
            box.bind('<<ComboboxSelected>>', command)
        self.edit_controls.append((box, 'readonly'))

    @staticmethod
    def make_table(parent, columns, widths):
        table = ttk.Treeview(parent, columns=columns, show='headings')
        vertical = ttk.Scrollbar(parent, orient='vertical', command=table.yview)
        horizontal = ttk.Scrollbar(parent, orient='horizontal', command=table.xview)
        table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        table.grid(row=0, column=0, sticky='nsew')
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)
        for name, width in zip(columns, widths):
            table.heading(name, text=name)
            table.column(name, width=width, minwidth=60)
        table.tag_configure('alternate', background='#f4f4f4')
        table.tag_configure('conflict', foreground='#b3261e')
        return table

    def select_sample(self, _=None):
        self.custom_path = None
        self.data_note.set(SAMPLE_NOTE)

    def load_json(self):
        path = filedialog.askopenfilename(title='Choose a scheduling dataset', initialdir=ROOT / 'data',
                                          filetypes=[('JSON datasets', '*.json')])
        if path:
            try:
                problem = load_problem(path)
            except (ValueError, KeyError, TypeError, OSError) as e:
                messagebox.showerror('Cannot load dataset', str(e))
                return
            self.custom_path = path
            self.dataset.set('Custom JSON')
            self.data_note.set(f'{Path(path).name} — {len(problem.courses)} courses, {len(problem.rooms)} rooms, '
                               f'{len(problem.instructors)} instructors, {len(problem.groups)} student groups')

    def set_busy(self, busy):
        self.busy = busy
        for control, normal_state in self.edit_controls:
            control.configure(state='disabled' if busy else normal_state)
        self.run_button.configure(state='disabled' if busy else 'normal')
        self.save_button.configure(state='normal' if self.result and not busy else 'disabled')
        if busy:
            self.progress.configure(mode='indeterminate')
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.configure(mode='determinate', value=0)

    def generate(self):
        if self.busy:
            return
        try:
            config = parse_settings({**{k: v.get() for k, v in self.values.items()},
                                     'selection': option_key(SELECTIONS, self.selection.get()),
                                     'crossover_type': option_key(CROSSOVERS, self.crossover_type.get()),
                                     'mutation_type': option_key(MUTATIONS, self.mutation_type.get())})
            problem = load_problem(self.custom_path) if self.custom_path else example_problem(int(self.dataset.get().split()[0]))
        except (ValueError, KeyError, TypeError, OSError, StopIteration) as e:
            messagebox.showerror('Check your settings', str(e))
            return
        algorithm = self.algorithm.get()
        self.set_busy(True)
        self.status.set(f'Generating {len(problem.courses)} courses using {algorithm}...')

        def work():
            try:
                if algorithm == 'Genetic Algorithm':
                    result = genetic_algorithm(problem, config, lambda g, s: self.queue.put(('progress', g, s)))
                else:
                    result = hill_climbing(problem, config.population * (config.generations + 1) - 1,
                                           config.seed, config.population)
                self.queue.put(('result', problem, result))
            except Exception as e:
                self.queue.put(('error', str(e)))
        Thread(target=work, daemon=True).start()

    def poll(self):
        latest = None
        while True:
            try:
                item = self.queue.get_nowait()
            except Empty:
                break
            if item[0] == 'progress':
                latest = item
                continue
            self.set_busy(False)
            if item[0] == 'error':
                self.status.set('Generation failed. Check the dataset and try again.')
                messagebox.showerror('Could not generate timetable', item[1])
            else:
                self.problem, self.result = item[1:]
                self.show_result()
                self.save_button.configure(state='normal')
        if latest and self.busy:
            _, generation, score = latest
            self.status.set(f'Generation {generation}: best hard {score.hard}, soft {score.soft}, '
                            f'fitness {score.fitness:.6f}')
        self.root.after(100, self.poll)

    def show_result(self):
        result, p = self.result, self.problem
        self.conflicts = conflicted_courses(p, result.chromosome)
        items = dict(summary_items(p, result))
        state = 'Feasible timetable (no hard violations)' if result.score.hard == 0 else 'Conflicts remain (shown in red)'
        self.status.set(f'{state} - {result.algorithm}')
        for name, var in self.summary.items():
            value = items.get(name, items.get('Iterations'))
            var.set(f'{value} iterations' if name == 'Generations' and 'Iterations' in items else value)
        for table in (self.table, self.constraints):
            table.delete(*table.get_children())
        order = sorted(range(len(p.courses)), key=lambda i: result.chromosome[i])
        for n, (i, row) in enumerate(zip(order, timetable_rows(p, result.chromosome))):
            tags = ('conflict',) if i in self.conflicts else ('alternate',) if n % 2 else ()
            self.table.insert('', 'end', values=row, tags=tags)
        for kind, details in (('Hard', result.score.hard_details), ('Soft', result.score.soft_details)):
            for name, count in details.items():
                self.constraints.insert('', 'end', values=(kind, name.replace('_', ' ').capitalize(), count))
        self.draw_grid()
        self.draw_plot()

    def draw_grid(self):
        c = self.grid_canvas
        c.delete('all')
        width = max(c.winfo_width(), 600)
        if not self.result:
            c.create_text(width / 2, 80, text='Generate a timetable to see the weekly grid.', fill='#556477')
            return
        p, chromosome = self.problem, self.result.chromosome
        instructors = {i.id: i.name for i in p.instructors}
        cells = defaultdict(list)
        for i, (course, (d, t, r)) in enumerate(zip(p.courses, chromosome)):
            cells[d, t].append((course, r, i))
        left, head, line = 105, 30, 17
        col = (width - left - 4) / len(p.days)
        chars = max(12, int(col / 7))
        for d, day in enumerate(p.days):
            x = left + d * col
            c.create_rectangle(x, 0, x + col, head, fill='#eaf0f7', outline='#c9d3df')
            c.create_text(x + col / 2, head / 2, text=day, font=('Segoe UI', 10, 'bold'), fill='#26374a')
        y = head
        for t, period in enumerate(p.periods):
            height = max(2, max(len(cells[d, t]) for d in range(len(p.days)))) * line * 2 + 10
            c.create_rectangle(0, y, left, y + height, fill='#eaf0f7', outline='#c9d3df')
            c.create_text(left / 2, y + height / 2, text=period, font=('Segoe UI', 9, 'bold'), fill='#26374a')
            for d in range(len(p.days)):
                x = left + d * col
                c.create_rectangle(x, y, x + col, y + height, fill='white', outline='#c9d3df')
                for k, (course, r, i) in enumerate(cells[d, t]):
                    color = '#b3261e' if i in self.conflicts else '#1d3b5c'
                    top = y + 5 + k * line * 2
                    c.create_text(x + 6, top, anchor='nw', fill=color, font=('Segoe UI', 9, 'bold'),
                                  text=f'{course.id} {course.name}'[:chars])
                    c.create_text(x + 6, top + line - 2, anchor='nw', fill='#5b6b7d', font=('Segoe UI', 8),
                                  text=f'{p.rooms[r].id} · {instructors[course.instructor]} · {", ".join(course.groups)}'[:chars + 6])
            y += height
        c.configure(scrollregion=(0, 0, width, y + 5))

    def draw_plot(self):
        c = self.canvas
        c.delete('all')
        width, height = max(c.winfo_width(), 200), max(c.winfo_height(), 150)
        if not self.result:
            c.create_text(width / 2, height / 2, text='Generate a timetable to see fitness convergence.', fill='#556477')
            return
        history = sample_points(self.result.history, 1000)
        left, top, right, bottom = 85, 30, width - 25, height - 50
        maximum = max(h['fitness'] for h in history) * 1.05
        last = max(1, history[-1]['generation'])
        for i in range(5):
            y = bottom - (bottom - top) * i / 4
            c.create_line(left, y, right, y, fill='#e3e8ee')
            c.create_text(left - 8, y, text=f'{maximum*i/4:.4f}', anchor='e', fill='#556477')
        c.create_line(left, top, left, bottom, right, bottom, fill='#8695a6')
        series = [('fitness', '#245fa5', 2)]
        if 'mean_fitness' in history[0]:
            series.insert(0, ('mean_fitness', '#a7b1bc', 1))
        for key, color, line_width in series:
            points = []
            for h in history:
                points.extend((left + (right - left) * h['generation'] / last,
                               bottom - (bottom - top) * h[key] / maximum))
            if len(points) >= 4:
                c.create_line(*points, fill=color, width=line_width)
            else:
                x, y = points
                c.create_oval(x - 3, y - 3, x + 3, y + 3, fill=color, outline='')
        c.create_text(left, 12, text='Best fitness (blue)' + (' and population mean (grey)' if len(series) > 1 else ''),
                      anchor='w', fill='#26374a')
        c.create_text(left, bottom + 15, text='0', fill='#556477')
        c.create_text(right, bottom + 15, text=str(self.result.generations), fill='#556477')
        c.create_text((left + right) / 2, height - 13,
                      text='Generation' if self.result.algorithm == 'Genetic Algorithm' else 'Iteration', fill='#26374a')

    def save(self):
        if not self.result:
            return
        folder = filedialog.askdirectory(title='Choose a folder for timetable, data and results', initialdir=ROOT / 'results')
        if not folder:
            return
        names = ['timetable.html', 'timetable.csv', 'convergence.csv', 'convergence.png', 'result.json', 'dataset.json']
        if any((Path(folder) / name).exists() for name in names):
            if not messagebox.askyesno('Replace previous exports?', 'This folder contains previous schedule exports. Replace those files?'):
                return
        try:
            save_all(self.problem, self.result, folder)
        except OSError as e:
            messagebox.showerror('Cannot save results', str(e))
            return
        messagebox.showinfo('Results saved', f'Saved timetable, convergence data and plot, dataset and full result to:\n{folder}')


def main(argv=None):
    parser = argparse.ArgumentParser(description='COMP338 university course scheduling with a genetic algorithm.')
    parser.add_argument('--cli', action='store_true', help='print the timetable in the console instead of opening the window')
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--courses', type=int, default=20, help='built-in example size, 1-50 (default 20)')
    source.add_argument('--data', help='JSON dataset file, for example data/sample_30.json')
    parser.add_argument('--algorithm', choices=('ga', 'hill'), default='ga')
    parser.add_argument('--population', type=int, default=Config.population)
    parser.add_argument('--generations', type=int, default=Config.generations)
    parser.add_argument('--mutation', type=float, default=Config.mutation, help='per-gene probability')
    parser.add_argument('--crossover', type=float, default=Config.crossover, help='per-pair probability')
    parser.add_argument('--elite', type=float, default=Config.elite_fraction, help='elitism fraction')
    parser.add_argument('--tournament', type=int, default=Config.tournament)
    parser.add_argument('--patience', type=int, default=Config.patience, help='stop after this many generations without improvement; 0 = never')
    parser.add_argument('--target-soft', type=int, default=Config.target_soft, help='stop once hard = 0 and soft <= this value')
    parser.add_argument('--selection', choices=SELECTIONS, default=Config.selection)
    parser.add_argument('--crossover-type', choices=CROSSOVERS, default=Config.crossover_type)
    parser.add_argument('--mutation-type', choices=MUTATIONS, default=Config.mutation_type)
    parser.add_argument('--unrestricted', action='store_true', help='sample genes from the whole grid; H4-H6 handled only by penalties')
    parser.add_argument('--seed', type=int, default=Config.seed)
    parser.add_argument('--save', help='folder for timetable.html/csv, convergence.csv/png, result.json and dataset.json')
    args = parser.parse_args(argv)
    if not args.cli:
        if tk is None:
            parser.error('Tkinter is not available here; use --cli')
        root = tk.Tk()
        SchedulerApp(root)
        root.mainloop()
        return
    try:
        problem = load_problem(args.data) if args.data else example_problem(args.courses)
        config = Config(population=args.population, generations=args.generations, mutation=args.mutation,
                        crossover=args.crossover, elite_fraction=args.elite, tournament=args.tournament,
                        patience=args.patience, target_soft=args.target_soft, seed=args.seed,
                        selection=args.selection, crossover_type=args.crossover_type,
                        mutation_type=args.mutation_type, restricted=not args.unrestricted).validate()
    except (ValueError, KeyError, TypeError, OSError) as e:
        parser.error(str(e))
    print(f'{len(problem.courses)} courses, {len(problem.instructors)} instructors, {len(problem.rooms)} rooms, '
          f'{len(problem.groups)} student groups, {len(problem.days)} days x {len(problem.periods)} periods\n')
    if args.algorithm == 'ga':
        result = genetic_algorithm(problem, config)
    else:
        result = hill_climbing(problem, args.population * (args.generations + 1) - 1, args.seed, args.population)
    print_report(problem, result)
    if args.save:
        save_all(problem, result, args.save)
        print(f'\nSaved results to {Path(args.save).resolve()}')


if __name__ == '__main__':
    main()
