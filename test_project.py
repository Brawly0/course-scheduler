from collections import Counter, defaultdict
from contextlib import redirect_stdout
from dataclasses import replace
from types import SimpleNamespace
import io
import json
import random
import tempfile
import unittest
from pathlib import Path
from main import Problem, Room, Instructor, Course, example_problem, save_problem, load_problem
from main import Evaluator, conflicted_courses, CATALOGUE, GROUPS, ROOT
from main import (Config, genetic_algorithm, hill_climbing, initialize_population, first_generation,
                  tournament_selection, roulette_wheel_selection, one_point_crossover, two_point_crossover,
                  random_mutation, swap_mutation, change_time_mutation, change_room_mutation,
                  SELECTIONS, CROSSOVERS, MUTATIONS, option_key)
from main import export_result, parse_settings, timetable_rows, main

UNARY = ('room_capacity', 'room_type', 'instructor_availability')


def fixture():
    return Problem(('Sun', 'Mon'), ('08', '09', '10', '11'),
                   (Room('L', 50, 'Lecture'), Room('B', 20, 'Lab')),
                   (Instructor('I1', 'One', ((1, 0),), (1, 2)), Instructor('I2', 'Two')),
                   (Course('C1', 'One', 30, 'I1', 'Lecture', ('G1',)),
                    Course('C2', 'Two', 30, 'I1', 'Lecture', ('G1',)),
                    Course('C3', 'Three', 15, 'I2', 'Lab', ('G2',))))


def reference_counts(problem, chromosome):
    teachers = {i.id: i for i in problem.instructors}
    hard, soft = dict.fromkeys(Evaluator.HARD, 0), dict.fromkeys(Evaluator.SOFT, 0)
    items = list(zip(problem.courses, chromosome))
    for x, (a, (d1, t1, r1)) in enumerate(items):
        for b, (d2, t2, r2) in items[x + 1:]:
            if (d1, t1) == (d2, t2):
                hard['instructor_conflict'] += a.instructor == b.instructor
                hard['room_conflict'] += r1 == r2
                hard['student_conflict'] += len(set(a.groups) & set(b.groups))
    for c, (d, t, r) in items:
        room, teacher = problem.rooms[r], teachers[c.instructor]
        hard['room_capacity'] += c.students > room.capacity
        hard['room_type'] += c.type != room.type
        hard['instructor_availability'] += (d, t) in teacher.unavailable
        soft['early_classes'] += t == 0
        soft['late_classes'] += t == len(problem.periods) - 1
        soft['instructor_preferences'] += bool(teacher.preferred_periods) and t not in teacher.preferred_periods
    for group in problem.groups:
        periods = defaultdict(set)
        for c, (d, t, r) in items:
            if group in c.groups:
                periods[d].add(t)
        soft['group_working_days'] += len(periods) - 1
        soft['student_gaps'] += sum(max(p) - min(p) + 1 - len(p) for p in periods.values())
    return hard, soft


class FitnessTests(unittest.TestCase):
    def test_feasible_and_exact_soft_counts(self):
        score = Evaluator(fixture()).evaluate(((0, 1, 0), (0, 2, 0), (0, 1, 1)))
        self.assertEqual((score.hard, score.soft, score.penalty, score.fitness), (0, 0, 0, 1))

    def test_collision_counts_are_pairs(self):
        score = Evaluator(fixture()).evaluate(((0, 1, 0), (0, 1, 0), (0, 1, 0)))
        self.assertEqual(score.hard_details, dict(instructor_conflict=1, room_conflict=3,
                         student_conflict=1, room_capacity=0, room_type=1, instructor_availability=0))

    def test_capacity_type_and_availability(self):
        score = Evaluator(fixture()).evaluate(((1, 0, 1), (0, 2, 0), (0, 1, 1)))
        self.assertEqual(score.hard, 3)
        for name in UNARY:
            self.assertEqual(score.hard_details[name], 1)

    def test_gaps_early_late_and_preferences(self):
        score = Evaluator(fixture()).evaluate(((0, 0, 0), (0, 3, 0), (0, 1, 1)))
        self.assertEqual(score.soft_details, dict(early_classes=1, late_classes=1,
                         student_gaps=2, instructor_preferences=2, group_working_days=0))
        self.assertEqual(score.fitness, 1 / 61)

    def test_working_days_and_no_cross_day_gaps(self):
        score = Evaluator(fixture()).evaluate(((0, 1, 0), (1, 2, 0), (0, 1, 1)))
        self.assertEqual(score.soft, 1)
        self.assertEqual(score.soft_details['group_working_days'], 1)

    def test_multiple_groups_count_each_affected_group(self):
        p = fixture()
        p = replace(p, courses=tuple(replace(c, groups=('G1', 'G2')) for c in p.courses[:2]))
        self.assertEqual(Evaluator(p).evaluate(((0, 1, 0), (0, 1, 0))).hard_details['student_conflict'], 2)

    def test_hard_dominates_soft(self):
        e = Evaluator(fixture())
        good = e.evaluate(((0, 0, 0), (0, 3, 0), (0, 1, 1)))
        bad = e.evaluate(((0, 1, 0), (0, 1, 0), (0, 1, 1)))
        self.assertLess(good.penalty, bad.penalty)

    def test_brief_penalty_examples(self):
        e = Evaluator(example_problem(20))
        self.assertEqual(e.soft_weight, 10)
        self.assertAlmostEqual(1 / (1 + e.soft_weight * 10), 0.0099, places=4)
        self.assertAlmostEqual(1 / (1 + e.soft_weight * 3), 0.0323, places=4)

    def test_fast_evaluator_matches_pairwise_definition(self):
        rng = random.Random(3)
        for size in (10, 30, 50):
            p = example_problem(size)
            e = Evaluator(p, restricted=False)
            for crowded in (False, True):
                for _ in range(60):
                    genes = tuple((rng.randrange(2), rng.randrange(4), rng.randrange(6)) if crowded
                                  else rng.choice(e.domains[0]) for _ in p.courses)
                    score = e.evaluate(genes)
                    self.assertEqual((score.hard_details, score.soft_details), reference_counts(p, genes))

    def test_invalid_chromosome(self):
        for genes in ((), ((8, 0, 0),) * 3, ((-1, 0, 0),) * 3):
            with self.assertRaises(ValueError):
                Evaluator(fixture()).evaluate(genes)

    def test_conflicted_courses(self):
        p = fixture()
        self.assertEqual(conflicted_courses(p, ((0, 1, 0), (0, 2, 0), (0, 1, 1))), set())
        self.assertEqual(conflicted_courses(p, ((0, 1, 0), (0, 1, 0), (0, 2, 1))), {0, 1})
        self.assertEqual(conflicted_courses(p, ((1, 0, 0), (0, 2, 0), (0, 1, 1))), {0})


class DatasetTests(unittest.TestCase):
    def test_first_ten_courses_follow_the_brief(self):
        p = example_problem(10)
        brief = [('Artificial Intelligence', 35, 'I01', 'Lecture'), ('Database', 40, 'I02', 'Lecture'),
                 ('Networks', 30, 'I03', 'Lecture'), ('Operating Systems', 35, 'I01', 'Lecture'),
                 ('Software Engineering', 45, 'I04', 'Lecture'), ('Algorithms', 40, 'I05', 'Lecture'),
                 ('Data Mining', 25, 'I06', 'Lecture'), ('Computer Graphics', 30, 'I07', 'Lab'),
                 ('Web Programming', 25, 'I08', 'Lab'), ('Machine Learning', 35, 'I06', 'Lecture')]
        self.assertEqual([(c.name, c.students, c.instructor, c.type) for c in p.courses], brief)
        self.assertEqual([(r.id, r.capacity, r.type) for r in p.rooms],
                         [('R101', 50, 'Lecture'), ('R102', 40, 'Lecture'), ('R103', 35, 'Lecture'),
                          ('R104', 25, 'Lecture'), ('LAB1', 30, 'Lab'), ('LAB2', 25, 'Lab')])
        ahmad = {i.id: i for i in p.instructors}['I01']
        self.assertEqual(ahmad.name, 'Dr. Ahmad')
        self.assertIn((1, 2), ahmad.unavailable)
        self.assertEqual(len(p.days) * len(p.periods) * len(p.rooms), 120)

    def test_every_size_is_valid_and_every_course_has_a_group(self):
        self.assertEqual({n for rows in GROUPS.values() for n in rows}, set(range(1, len(CATALOGUE) + 1)))
        for size in range(1, len(CATALOGUE) + 1):
            self.assertEqual(len(example_problem(size).courses), size)
        for size in (20, 30, 40):
            p = example_problem(size)
            self.assertTrue(10 <= len(p.instructors) <= 20 and len(p.groups) >= 3)

    def test_sample_files_match_the_generator(self):
        for size in (10, 20, 30, 40, 50):
            self.assertEqual(load_problem(ROOT / 'data' / f'sample_{size}.json'), example_problem(size))

    def test_slot_numbers_are_unique(self):
        p = example_problem(10)
        genes = [(d, t, r) for d in range(5) for t in range(4) for r in range(6)]
        self.assertEqual(sorted(p.slot_number(g) for g in genes), list(range(120)))
        self.assertEqual(p.describe((1, 2, 1)), 'Monday 10:00 R102')


class OperatorTests(unittest.TestCase):
    A = tuple((i, 0, 0) for i in range(8))
    B = tuple((i, 1, 0) for i in range(8))

    def test_operators_preserve_unary_constraints(self):
        e, rng = Evaluator(example_problem(50)), random.Random(7)
        pop = initialize_population(e, 10, rng)
        children = [*two_point_crossover(pop[0], pop[1], 1, rng), *one_point_crossover(pop[2], pop[3], 1, rng)]
        for mutate in (random_mutation, swap_mutation, change_time_mutation, change_room_mutation):
            for c in pop + [mutate(child, e, 1, rng) for child in children]:
                score = e.evaluate(c)
                for name in UNARY:
                    self.assertEqual(score.hard_details[name], 0)

    def test_crossover_preserves_course_positions_and_parents(self):
        a, b = self.A, self.B
        for crossover in (one_point_crossover, two_point_crossover):
            for child in crossover(a, b, 1, random.Random(4)):
                for i, gene in enumerate(child):
                    self.assertIn(gene, (a[i], b[i]))
            self.assertEqual(crossover(a, b, 0, random.Random(0)), (a, b))
            self.assertEqual(crossover(a[:1], b[:1], 1, random.Random(0)), (a[:1], b[:1]))

    def test_one_point_crossover_uses_one_inner_cut(self):
        a, b = self.A, self.B
        for seed in range(30):
            c1, c2 = one_point_crossover(a, b, 1, random.Random(seed))
            cut = next(i for i, gene in enumerate(c1) if gene != a[i])
            self.assertTrue(0 < cut < 8)
            self.assertEqual((c1, c2), (a[:cut] + b[cut:], b[:cut] + a[cut:]))

    def test_two_point_crossover_exchanges_an_inner_segment(self):
        a, b = self.A, self.B
        for seed in range(30):
            c1, c2 = two_point_crossover(a, b, 1, random.Random(seed))
            changed = [i for i, gene in enumerate(c1) if gene != a[i]]
            self.assertTrue(changed and changed[0] > 0 and changed[-1] < 7)
            self.assertEqual(changed, list(range(changed[0], changed[-1] + 1)))
            self.assertEqual(c2, tuple(a[i] if i in changed else b[i] for i in range(8)))

    def test_mutation_operators(self):
        e, rng = Evaluator(example_problem(20)), random.Random(5)
        c = initialize_population(e, 1, rng)[0]
        self.assertEqual(random_mutation(c, e, 0, rng), c)
        self.assertNotEqual(random_mutation(c, e, 1, rng), c)
        moved = change_time_mutation(c, e, 1, rng)
        self.assertEqual([g[2] for g in moved], [g[2] for g in c])
        moved = change_room_mutation(c, e, 1, rng)
        self.assertEqual([g[:2] for g in moved], [g[:2] for g in c])
        swapped = swap_mutation(c, e, 1, rng)
        self.assertNotEqual(swapped, c)
        self.assertEqual(Counter(g[:2] for g in swapped), Counter(g[:2] for g in c))
        self.assertEqual(Counter(g[2] for g in swapped), Counter(g[2] for g in c))

    def test_swap_mutation_exchanges_two_courses(self):
        e = Evaluator(fixture())
        c = ((0, 1, 0), (1, 2, 0), (0, 3, 1))

        class Fixed:
            def random(self):
                return 0.0 if not hasattr(self, 'done') else 1.0

            def randrange(self, _):
                self.done = True
                return 0
        swapped = swap_mutation(c, e, 0.5, Fixed())
        self.assertEqual(swapped, ((1, 2, 0), (0, 1, 0), (0, 3, 1)))

    def test_tournament_selects_best_sampled(self):
        class FixedRandom:
            def randrange(self, _):
                return next(self.values)
        rng = FixedRandom()
        rng.values = iter([0, 1, 0])
        e = Evaluator(fixture())
        pop = [((0, 1, 0), (0, 1, 0), (0, 1, 0)), ((0, 1, 0), (0, 2, 0), (0, 1, 1))]
        self.assertEqual(tournament_selection(pop, [e.evaluate(c) for c in pop], rng, 3), pop[1])

    def test_roulette_is_fitness_proportionate(self):
        class Fixed:
            def __init__(self, value):
                self.value = value

            def random(self):
                return self.value
        scores = [SimpleNamespace(fitness=f) for f in (0.1, 0.3, 0.6)]
        picks = [roulette_wheel_selection('abc', scores, Fixed(v)) for v in (0.05, 0.2, 0.39, 0.41, 0.99)]
        self.assertEqual(picks, ['a', 'b', 'b', 'c', 'c'])
        rng = random.Random(1)
        counts = Counter(roulette_wheel_selection('abc', scores, rng) for _ in range(20000))
        self.assertAlmostEqual(counts['c'] / 20000, 0.6, delta=0.02)


class AlgorithmTests(unittest.TestCase):
    def test_reproducibility_elitism_and_evaluation_budget(self):
        p, config = example_problem(), Config(population=21, generations=25, patience=0)
        a, b = genetic_algorithm(p, config), genetic_algorithm(p, config)
        self.assertEqual(a.chromosome, b.chromosome)
        self.assertEqual(a.history, b.history)
        self.assertEqual(a.evaluations, 21 * 26)
        self.assertTrue(all(x['penalty'] >= y['penalty'] for x, y in zip(a.history, a.history[1:])))
        self.assertTrue(all(0 <= h['diversity'] < 1 and h['mean_fitness'] <= h['fitness'] for h in a.history))
        self.assertEqual(a.score, Evaluator(p).evaluate(a.chromosome))

    def test_every_operator_combination_runs(self):
        p = example_problem(12)
        for selection in SELECTIONS:
            for crossover in CROSSOVERS:
                for mutation in MUTATIONS:
                    r = genetic_algorithm(p, Config(population=12, generations=5, seed=1, selection=selection,
                                                    crossover_type=crossover, mutation_type=mutation))
                    self.assertEqual(r.score, Evaluator(p).evaluate(r.chromosome))
                    self.assertEqual(r.evaluations, 12 * 6)

    def test_small_example_finds_feasible_schedule(self):
        result = genetic_algorithm(example_problem(), Config(population=40, generations=100, patience=0))
        self.assertEqual(result.score.hard, 0)

    def test_unrestricted_encoding_relies_on_penalties(self):
        p = example_problem(10)
        e = Evaluator(p, restricted=False)
        self.assertEqual(len(e.domains[0]), 120)
        start = initialize_population(e, 20, random.Random(2))
        self.assertTrue(any(e.evaluate(c).hard_details['room_type'] for c in start))
        result = genetic_algorithm(p, Config(population=60, generations=200, patience=0, restricted=False))
        self.assertEqual(result.score.hard, 0)

    def test_termination(self):
        p = example_problem(1)
        result = genetic_algorithm(p, Config(generations=0))
        self.assertEqual(result.generations, 0)
        result = genetic_algorithm(p, Config(target_soft=100))
        self.assertEqual((result.generations, result.reason), (0, 'target soft score'))
        result = genetic_algorithm(p, Config(mutation=0, crossover=0, patience=2))
        self.assertEqual((result.generations, result.reason), (2, 'no improvement'))

    def test_hill_budget_monotonicity_and_sampled_history(self):
        result = hill_climbing(example_problem(), 200, 42)
        self.assertEqual(result.evaluations, 201)
        self.assertTrue(all(x['penalty'] >= y['penalty'] for x, y in zip(result.history, result.history[1:])))
        sampled = hill_climbing(example_problem(), 1000, 1, record_every=100)
        self.assertEqual([h['evaluations'] for h in sampled.history],
                         [1] + list(range(100, 1001, 100)) + [1001])
        self.assertEqual(first_generation(sampled.history, lambda h: h['penalty'] == sampled.score.penalty) is not None, True)

    def test_invalid_config_and_impossible_input(self):
        for config in (Config(population=1), Config(mutation=-.1), Config(crossover=1.1),
                       Config(elite_fraction=1), Config(generations=-1), Config(mutation=float('nan')),
                       Config(selection='rank'), Config(crossover_type='uniform'), Config(mutation_type='x')):
            with self.assertRaises(ValueError):
                config.validate()
        p = fixture()
        with self.assertRaises(ValueError):
            Evaluator(replace(p, courses=(replace(p.courses[0], students=1000),)))
        with self.assertRaises(ValueError):
            Evaluator(replace(p, instructors=(replace(p.instructors[0], unavailable=tuple(
                (d, t) for d in range(2) for t in range(4))), p.instructors[1])))

    def test_collectively_infeasible_problem_is_reported(self):
        p = Problem(('Sun',), ('09',), (Room('R', 50, 'Lecture'),),
                    (Instructor('I', 'One'),),
                    tuple(Course(f'C{i}', str(i), 20, 'I', 'Lecture', ('G',)) for i in range(2)))
        result = genetic_algorithm(p, Config(population=4, generations=3, patience=0))
        self.assertEqual(result.score.hard, 3)
        with tempfile.TemporaryDirectory() as tmp:
            export_result(p, result, tmp)
            self.assertIn('Conflicts remain', (Path(tmp) / 'timetable.html').read_text(encoding='utf-8'))

    def test_json_roundtrip_and_exports(self):
        p = example_problem()
        with tempfile.TemporaryDirectory() as tmp:
            save_problem(p, Path(tmp) / 'data.json')
            self.assertEqual(p, load_problem(Path(tmp) / 'data.json'))
            result = genetic_algorithm(p, Config(generations=2))
            export_result(p, result, tmp)
            data = json.loads((Path(tmp) / 'result.json').read_text())
            self.assertEqual(len(data['chromosome']), 10)
            self.assertTrue((Path(tmp) / 'timetable.html').is_file())


class InterfaceTests(unittest.TestCase):
    def test_settings_from_form(self):
        config = parse_settings(dict(population='50', generations='100', mutation='0.1', crossover='0.9', seed='3'))
        self.assertEqual((config.population, config.generations, config.mutation, config.seed), (50, 100, .1, 3))
        config = parse_settings(dict(population='50', generations='100', mutation='0.1', crossover='0.9', seed='3',
                                     elite='0.1', tournament='3', patience='0', target='12',
                                     selection='roulette', crossover_type='one_point', mutation_type='swap'))
        self.assertEqual((config.elite_fraction, config.tournament, config.patience, config.target_soft,
                          config.selection, config.crossover_type, config.mutation_type),
                         (.1, 3, 0, 12, 'roulette', 'one_point', 'swap'))

    def test_reject_bad_form_settings(self):
        values = dict(population='50', generations='100', mutation='0.1', crossover='0.9', seed='3')
        for key, value in [('population', 'abc'), ('mutation', '5'), ('generations', '-1'), ('population', '50000'),
                           ('selection', 'rank')]:
            with self.assertRaises(ValueError):
                parse_settings({**values, key: value})

    def test_option_labels(self):
        self.assertEqual(option_key(SELECTIONS, 'Roulette wheel'), 'roulette')
        self.assertEqual(option_key(MUTATIONS, 'Swap two courses'), 'swap')

    def test_rows_preserve_identity_and_sort_chronologically(self):
        problem = example_problem(2)
        rows = timetable_rows(problem, ((1, 2, 0), (0, 1, 1)))
        self.assertEqual([r[2] for r in rows], ['C02', 'C01'])
        self.assertEqual(rows[0][5], 'R102')

    def test_console_mode_prints_section_22_summary(self):
        out = io.StringIO()
        with redirect_stdout(out):
            main(['--cli', '--courses', '10', '--population', '30', '--generations', '60', '--seed', '3'])
        text = out.getvalue()
        for label in ('Courses scheduled: 10/10', 'Hard violations:   0', 'Soft violations:',
                      'Final penalty:', 'Best fitness:', 'Generations:', 'Chromosome (slot numbers):'):
            self.assertIn(label, text)


if __name__ == '__main__':
    unittest.main()
