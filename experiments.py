import argparse
import json
import platform
import textwrap
from dataclasses import replace, asdict
from pathlib import Path
from statistics import mean, stdev
from time import perf_counter
from types import SimpleNamespace
from main import (Config, genetic_algorithm, hill_climbing, example_problem, save_problem, write_csv,
                  export_result, plot_convergence, first_generation, SELECTIONS, CROSSOVERS, MUTATIONS)

BASE_SIZE = 30
STUDIES = {
    'population': ('population', [20, 50, 100, 200], 'Experiment 1: population size'),
    'mutation': ('mutation', [0.01, 0.05, 0.10, 0.20], 'Experiment 2: mutation rate'),
    'crossover': ('crossover', [0.60, 0.80, 0.90], 'Experiment 3: crossover rate'),
    'size': (None, [10, 20, 30, 40, 50], 'Experiment 4: dataset size'),
    'selection': ('selection', ['tournament', 'roulette'], 'Advanced A: selection method'),
    'crossover_type': ('crossover_type', ['one_point', 'two_point'], 'Advanced B: crossover method'),
    'mutation_type': ('mutation_type', ['random', 'swap', 'time', 'room'], 'Advanced C: mutation strategy'),
    'encoding': ('restricted', [True, False], 'Extra: gene domain'),
}
BRIEF_TABLE = [(20, 0.01), (20, 0.05), (50, 0.01), (50, 0.05), (100, 0.05), (200, 0.05)]
BUDGETS = (50, 100, 250, 500)

CATEGORICAL = ('#2a78d6', '#eb6834', '#1baf7a', '#eda100')
ORDINAL = {3: ('#86b6ef', '#2a78d6', '#104281'), 4: ('#86b6ef', '#3987e5', '#1c5cab', '#0d366b')}
INK, INK2, MUTED, GRID, AXIS, SURFACE = '#0b0b0b', '#52514e', '#898781', '#e1e0d9', '#c3c2b7', '#fcfcfb'


def value_label(study, value):
    if study == 'selection':
        return SELECTIONS[value][0]
    if study == 'crossover_type':
        return CROSSOVERS[value][0]
    if study == 'mutation_type':
        return MUTATIONS[value][0]
    if study == 'encoding':
        return 'Restricted domains' if value else 'Unrestricted (penalty only)'
    if study in ('mutation', 'crossover'):
        return f'{value:.0%}'
    if study == 'size':
        return f'{value} courses'
    return str(value)


def config_for(base, study, value, seed):
    field = STUDIES[study][0]
    return replace(base, seed=seed, **({field: value} if field else {}))


def metrics(result):
    history = result.history
    return dict(fitness=result.score.fitness, hard=result.score.hard, soft=result.score.soft,
                penalty=result.score.penalty, runtime=round(result.runtime, 4), generations=result.generations,
                gen_feasible=first_generation(history, lambda h: h['hard'] == 0),
                gen_best=first_generation(history, lambda h: h['penalty'] == result.score.penalty),
                evaluations=result.evaluations, final_diversity=round(history[-1]['diversity'], 4))


def average_curves(histories):
    return {key: [round(mean(h[g][key] for h in histories), 8) for g in range(len(histories[0]))]
            for key in ('fitness', 'hard', 'soft', 'diversity')}


def sd(values):
    values = list(values)
    return stdev(values) if len(values) > 1 else 0.0


def summarize(study, value, label, group):
    feasible = [r['gen_feasible'] for r in group if r['gen_feasible'] is not None]
    return dict(study=study, value=value, label=label, runs=len(group),
                mean_fitness=mean(r['fitness'] for r in group), sd_fitness=sd(r['fitness'] for r in group),
                mean_hard=mean(r['hard'] for r in group), mean_soft=mean(r['soft'] for r in group),
                sd_soft=sd(r['soft'] for r in group), best_soft=min(r['soft'] for r in group),
                worst_soft=max(r['soft'] for r in group), feasible_rate=mean(r['hard'] == 0 for r in group),
                mean_gen_feasible=mean(feasible) if feasible else None,
                mean_gen_best=mean(r['gen_best'] for r in group), mean_runtime=mean(r['runtime'] for r in group),
                mean_diversity=mean(r['final_diversity'] for r in group))


def run_suite(args, output):
    started = perf_counter()
    base = Config(generations=args.generations, patience=0)
    problems = {size: example_problem(size) for size in STUDIES['size'][1]}
    for size, problem in problems.items():
        save_problem(problem, output / 'datasets' / f'{size}_courses.json')
    jobs = [(study, value, value if study == 'size' else BASE_SIZE, config_for(base, study, value, seed))
            for study, (_, values, _) in STUDIES.items() for value in values for seed in args.seeds]
    jobs += [('brief_table', f'{p}/{m}', BASE_SIZE, replace(base, seed=seed, population=p, mutation=m))
             for p, m in BRIEF_TABLE for seed in args.seeds]
    unique = list(dict.fromkeys((size, config) for _, _, size, config in jobs))
    done, histories, representative = {}, {}, None
    for n, (size, config) in enumerate(unique, 1):
        result = genetic_algorithm(problems[size], config)
        done[size, config] = metrics(result)
        histories[size, config] = [{k: h[k] for k in ('fitness', 'hard', 'soft', 'diversity')} for h in result.history]
        if size == BASE_SIZE and config == replace(base, seed=args.seeds[0]):
            representative = result
        c = config
        print(f'[{n:3}/{len(unique)}] {size} courses, pop {c.population}, mut {c.mutation}, xo {c.crossover}, '
              f'{c.selection}/{c.crossover_type}/{c.mutation_type}{"" if c.restricted else "/unrestricted"}, '
              f'seed {c.seed}: hard {result.score.hard}, soft {result.score.soft} ({result.runtime:.1f}s)', flush=True)
    rows, seen = [], set()
    for study, value, size, config in jobs:
        key = (size, config)
        rows.append(dict(study=study, value=value, seed=config.seed, size=size, population=config.population,
                         mutation=config.mutation, crossover=config.crossover, selection=config.selection,
                         crossover_type=config.crossover_type, mutation_type=config.mutation_type,
                         restricted=config.restricted, **done[key], shared=key in seen))
        seen.add(key)
    summary, curves = [], {}
    for study, (_, values, _) in STUDIES.items():
        for value in values:
            group = [r for r in rows if r['study'] == study and r['value'] == value]
            summary.append(summarize(study, value, value_label(study, value), group))
            size = value if study == 'size' else BASE_SIZE
            curves[f'{study}|{value}'] = average_curves(
                [histories[size, config_for(base, study, value, seed)] for seed in args.seeds])
    brief = []
    for p, m in BRIEF_TABLE:
        group = [r for r in rows if r['study'] == 'brief_table' and r['value'] == f'{p}/{m}']
        brief.append(dict(population=p, mutation=m, crossover=base.crossover, generations=base.generations,
                          **summarize('brief_table', f'{p}/{m}', f'P={p}, mutation {m:.0%}', group)))
    baseline = curves[f'population|{base.population}']
    budgets = [dict(generations=g, evaluations=base.population * (g + 1), mean_fitness=baseline['fitness'][g],
                    mean_soft=baseline['soft'][g], mean_hard=baseline['hard'][g])
               for g in BUDGETS if g <= args.generations]

    comparison, hill_histories, first_hill = [], [], None
    for seed in args.seeds:
        key = (BASE_SIZE, replace(base, seed=seed))
        ga = done[key]
        hill = hill_climbing(problems[BASE_SIZE], ga['evaluations'] - 1, seed, base.population)
        first_hill = first_hill or hill
        hill_histories.append(hill.history[1:])
        evals = lambda history, test: next((h['evaluations'] for h in history if test(h)), None)
        comparison.append(dict(algorithm='Genetic Algorithm', seed=seed, fitness=ga['fitness'], hard=ga['hard'],
                               soft=ga['soft'], penalty=ga['penalty'], runtime=ga['runtime'],
                               evaluations=ga['evaluations'],
                               evals_to_feasible=None if ga['gen_feasible'] is None else base.population * (ga['gen_feasible'] + 1),
                               evals_to_best=base.population * (ga['gen_best'] + 1)))
        comparison.append(dict(algorithm='Hill Climbing', seed=seed, fitness=hill.score.fitness, hard=hill.score.hard,
                               soft=hill.score.soft, penalty=hill.score.penalty, runtime=round(hill.runtime, 4),
                               evaluations=hill.evaluations,
                               evals_to_feasible=evals(hill.history, lambda h: h['hard'] == 0),
                               evals_to_best=evals(hill.history, lambda h: h['penalty'] == hill.score.penalty)))
        print(f'hill climbing seed {seed}: hard {hill.score.hard}, soft {hill.score.soft} ({hill.runtime:.1f}s)', flush=True)
    ga_curve = [baseline['fitness'][g] for g in range(len(baseline['fitness']))]
    comparison_curves = {
        'Genetic Algorithm': dict(evaluations=[base.population * (g + 1) for g in range(len(ga_curve))], fitness=ga_curve),
        'Hill Climbing': dict(evaluations=[h['evaluations'] for h in hill_histories[0]],
                              fitness=[round(mean(run[i]['fitness'] for run in hill_histories), 8)
                                       for i in range(len(hill_histories[0]))])}

    export_result(problems[BASE_SIZE], representative, output / 'representative')
    export_result(problems[BASE_SIZE], first_hill, output / 'hill_climbing')
    meta = dict(seeds=args.seeds, generations=args.generations, base_size=BASE_SIZE, base_config=asdict(base),
                unique_ga_runs=len(unique), hill_climbing_runs=len(args.seeds),
                total_minutes=round((perf_counter() - started) / 60, 2), python=platform.python_version(),
                platform=platform.platform(), processor=platform.processor(),
                design='one factor at a time; runs shared between studies are executed once and reused',
                representative_seed=args.seeds[0])
    data = dict(meta=meta, summary=summary, brief_table=brief, budgets=budgets, comparison=comparison,
                curves=curves, comparison_curves=comparison_curves, runs=rows)
    (output / 'results.json').write_text(json.dumps(data, indent=1), encoding='utf-8')
    write_csv(output / 'runs.csv', rows)
    write_csv(output / 'summary.csv', summary)
    write_csv(output / 'brief_results_table.csv', brief)
    write_csv(output / 'generation_budget.csv', budgets)
    write_csv(output / 'algorithm_comparison.csv', comparison)
    write_csv(output / 'manifest.csv', [{k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in meta.items()}])


def pyplot():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        'font.family': 'sans-serif', 'font.sans-serif': ['Segoe UI', 'DejaVu Sans'], 'font.size': 9.5,
        'figure.facecolor': SURFACE, 'axes.facecolor': SURFACE, 'savefig.facecolor': SURFACE,
        'axes.edgecolor': AXIS, 'axes.linewidth': 0.8, 'axes.labelcolor': INK2, 'axes.titlecolor': INK,
        'axes.titlesize': 10.5, 'axes.titleweight': 'semibold', 'axes.spines.top': False,
        'axes.spines.right': False, 'axes.grid': True, 'axes.grid.axis': 'y', 'grid.color': GRID,
        'grid.linewidth': 0.7, 'axes.axisbelow': True, 'xtick.color': AXIS, 'ytick.color': AXIS,
        'xtick.labelcolor': INK2, 'ytick.labelcolor': INK2, 'legend.frameon': False, 'legend.fontsize': 8.5,
        'legend.labelcolor': INK2, 'lines.linewidth': 1.8, 'savefig.dpi': 170, 'figure.titlesize': 12,
        'figure.titleweight': 'semibold'})
    return plt


def colours(study, n):
    return ORDINAL[n] if study in ('population', 'mutation', 'crossover') else CATEGORICAL[:n]


def rows_for(data, study):
    return [s for s in data['summary'] if s['study'] == study]


def wrap(text, width=13):
    return textwrap.fill(text, width)


def legend_below(ax, columns=2):
    ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.2), ncol=columns)


def convergence_panels(plt, data, studies, path, title):
    fig, axes = plt.subplots(1, len(studies), figsize=(3.5 * len(studies) + 0.5, 4.3), sharey=True,
                             layout='constrained')
    for ax, study in zip(axes, studies):
        _, values, name = STUDIES[study]
        for value, colour in zip(values, colours(study, len(values))):
            curve = data['curves'][f'{study}|{value}']['fitness']
            ax.plot(range(len(curve)), curve, color=colour, label=value_label(study, value))
        ax.set_title(name.split(': ')[1].capitalize())
        ax.set_xlabel('Generation')
        ax.set_ylim(bottom=0)
        legend_below(ax, 2 if len(values) > 2 or study == 'encoding' else len(values))
    axes[0].set_ylabel('Best fitness (mean of seeds)')
    fig.suptitle(title)
    fig.savefig(path)
    plt.close(fig)


def mutation_figure(plt, data, path):
    _, values, _ = STUDIES['mutation']
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.1), layout='constrained')
    for value, colour in zip(values, colours('mutation', len(values))):
        curve = data['curves'][f'mutation|{value}']
        axes[0].plot(range(len(curve['fitness'])), curve['fitness'], color=colour, label=f'Mutation {value:.0%}')
        axes[1].plot(range(len(curve['diversity'])), curve['diversity'], color=colour, label=f'Mutation {value:.0%}')
    axes[0].set(title='Best fitness', xlabel='Generation', ylabel='Best fitness (mean of seeds)')
    axes[1].set(title='Population diversity', xlabel='Generation', ylabel='Diversity (0 = all identical)')
    for ax in axes:
        ax.set_ylim(bottom=0)
    fig.legend(*axes[0].get_legend_handles_labels(), loc='outside lower center', ncol=4)
    fig.suptitle('Why the mutation rate matters: exploitation versus exploration')
    fig.savefig(path)
    plt.close(fig)


def parameter_figure(plt, data, path):
    studies = ('population', 'mutation', 'crossover')
    fig, axes = plt.subplots(2, 3, figsize=(12, 6.2), layout='constrained')
    for col, study in enumerate(studies):
        rows = rows_for(data, study)
        x = list(range(len(rows)))
        top, bottom = axes[0, col], axes[1, col]
        top.errorbar(x, [r['mean_fitness'] for r in rows], yerr=[r['sd_fitness'] for r in rows], color=CATEGORICAL[0],
                     ecolor=INK2, elinewidth=1, capsize=3, marker='o', markersize=6)
        top.set_title(STUDIES[study][2].split(': ')[1].capitalize())
        bottom.bar(x, [r['mean_runtime'] for r in rows], width=0.55, color=CATEGORICAL[0], edgecolor=SURFACE, linewidth=2)
        for ax in (top, bottom):
            ax.set_xticks(x, [r['label'] for r in rows])
    axes[0, 0].set_ylabel('Best fitness (mean ± SD)')
    axes[1, 0].set_ylabel('CPU time in seconds (mean)')
    fig.suptitle(f'Experiments 1-3 on the {BASE_SIZE}-course dataset ({len(data["meta"]["seeds"])} seeds each)')
    fig.savefig(path)
    plt.close(fig)


def operator_figure(plt, data, path):
    studies = ('selection', 'crossover_type', 'mutation_type', 'encoding')
    fig, axes = plt.subplots(1, 4, figsize=(13.5, 3.9), sharey=True, layout='constrained',
                             gridspec_kw={'width_ratios': [2, 2, 4, 2]})
    for ax, study in zip(axes, studies):
        rows = rows_for(data, study)
        x = list(range(len(rows)))
        ax.errorbar(x, [r['mean_fitness'] for r in rows], yerr=[r['sd_fitness'] for r in rows], fmt='o',
                    color=CATEGORICAL[0], ecolor=INK2, elinewidth=1, capsize=3, markersize=7)
        ax.set_xticks(x, [wrap(r['label']) for r in rows])
        ax.set_xlim(-0.6, len(rows) - 0.4)
        ax.set_title(STUDIES[study][2].split(': ')[1].capitalize())
    axes[0].set_ylabel('Best fitness (mean ± SD)')
    fig.suptitle('Advanced comparisons A-C and the gene-domain design choice')
    fig.savefig(path)
    plt.close(fig)


def size_figure(plt, data, path):
    rows = rows_for(data, 'size')
    x = [r['value'] for r in rows]
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 3.7), layout='constrained')
    axes[0].errorbar(x, [r['mean_soft'] for r in rows], yerr=[r['sd_soft'] for r in rows], color=CATEGORICAL[0],
                     ecolor=INK2, elinewidth=1, capsize=3, marker='o', markersize=6)
    axes[0].set(title='Soft violations of the best timetable', ylabel='Soft violations (mean ± SD)')
    axes[1].plot(x, [r['mean_runtime'] for r in rows], color=CATEGORICAL[0], marker='o', markersize=6)
    axes[1].set(title=f"CPU time for {data['meta']['generations']} generations", ylabel='CPU seconds (mean)')
    axes[2].plot(x, [r['mean_gen_feasible'] for r in rows], color=CATEGORICAL[0], marker='o', markersize=6,
                 label='First feasible timetable')
    axes[2].plot(x, [r['mean_gen_best'] for r in rows], color=CATEGORICAL[1], marker='s', markersize=6,
                 label='Final best found')
    axes[2].set(title='When the search found it', ylabel='Generation (mean)')
    legend_below(axes[2])
    for ax in axes:
        ax.set_xticks(x)
        ax.set_xlabel('Number of courses')
        ax.set_ylim(bottom=0)
    fig.suptitle('Experiment 4: effect of problem size (hard violations were 0 in every run)'
                 if all(r['mean_hard'] == 0 for r in rows) else 'Experiment 4: effect of problem size')
    fig.savefig(path)
    plt.close(fig)


def comparison_figure(plt, data, path):
    curves, rows = data['comparison_curves'], data['comparison']
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.8), layout='constrained',
                             gridspec_kw={'width_ratios': [2.2, 1.6, 1]})
    for (name, curve), colour in zip(curves.items(), CATEGORICAL):
        axes[0].plot(curve['evaluations'], curve['fitness'], color=colour, label=name)
    axes[0].set(title='Convergence at equal evaluation budget', xlabel='Fitness evaluations',
                ylabel='Best fitness (mean of seeds)')
    axes[0].set_ylim(bottom=0)
    axes[0].legend(loc='lower right')
    seeds = data['meta']['seeds']
    for (name, marker, shift), colour in zip((('Genetic Algorithm', 'o', -0.12), ('Hill Climbing', 's', 0.12)), CATEGORICAL):
        values = [r['soft'] for r in rows if r['algorithm'] == name]
        axes[1].scatter([i + shift for i in range(len(seeds))], values, color=colour, marker=marker, s=36,
                        edgecolors=SURFACE, linewidths=1.5, label=name, zorder=3)
    axes[1].set_xticks(range(len(seeds)), seeds)
    axes[1].set(title='Final soft violations per seed', xlabel='Seed', ylabel='Soft violations (lower is better)')
    axes[1].legend(loc='best')
    names = list(curves)
    runtime = [mean(r['runtime'] for r in rows if r['algorithm'] == n) for n in names]
    axes[2].bar(range(len(names)), runtime, width=0.55, color=CATEGORICAL[:len(names)], edgecolor=SURFACE, linewidth=2)
    axes[2].set_xticks(range(len(names)), [wrap(n, 10) for n in names])
    axes[2].set(title='CPU time', ylabel='CPU seconds (mean)')
    fig.suptitle(f'Advanced D: genetic algorithm versus hill climbing ({BASE_SIZE} courses)')
    fig.savefig(path)
    plt.close(fig)


def load_result(path):
    raw = json.loads(Path(path).read_text(encoding='utf-8'))
    return SimpleNamespace(**{**raw, 'score': SimpleNamespace(**raw['score'])})


def render(output):
    data = json.loads((output / 'results.json').read_text(encoding='utf-8'))
    plt = pyplot()
    plot_convergence(load_result(output / 'representative' / 'result.json'), output / 'convergence.png')
    plot_convergence(load_result(output / 'hill_climbing' / 'result.json'), output / 'hill_climbing' / 'convergence.png')
    convergence_panels(plt, data, ('population', 'mutation', 'crossover'), output / 'convergence_parameters.png',
                       'Generation vs best fitness for experiments 1-3')
    convergence_panels(plt, data, ('selection', 'crossover_type', 'mutation_type', 'encoding'),
                       output / 'convergence_operators.png', 'Generation vs best fitness for the operator comparisons')
    mutation_figure(plt, data, output / 'mutation_diversity.png')
    parameter_figure(plt, data, output / 'parameter_studies.png')
    operator_figure(plt, data, output / 'operator_comparison.png')
    size_figure(plt, data, output / 'size_scaling.png')
    comparison_figure(plt, data, output / 'ga_vs_hill_climbing.png')
    write_report(data, output)
    print(f'Finished figures and report: {output.resolve()}', flush=True)


def number(value, digits=0):
    return '-' if value is None else f'{value:.{digits}f}'


def write_report(data, output):
    meta, summary = data['meta'], data['summary']
    base = meta['base_config']
    lines = ['# Experimental results', '',
             f"Measured runs on {meta['platform']} with Python {meta['python']}. Seeds {meta['seeds']}; "
             f"{meta['generations']} generations per run; {meta['unique_ga_runs']} distinct GA runs and "
             f"{meta['hill_climbing_runs']} hill-climbing runs took {meta['total_minutes']:.1f} minutes.", '',
             f"Baseline: {meta['base_size']} courses, population {base['population']}, mutation {base['mutation']} per gene, "
             f"crossover {base['crossover']} per pair, {base['selection']} selection (size {base['tournament']}), "
             f"{base['crossover_type'].replace('_', '-')} crossover, {base['mutation_type']} mutation, "
             f"{base['elite_fraction']:.0%} elitism. One factor changes at a time. Stagnation stopping is off, so every run "
             f"uses the full budget. Runs that appear in several studies (the baseline) are executed once and reused.", '',
             '"Best found at gen." is the first generation that reached the run\'s final best penalty; "first feasible" is '
             'the first generation with zero hard violations. Diversity is the share of genes that differ from the most '
             'common gene at the same position in the final population. Runtime is the CPU time of the Python '
             'process (time.process_time), so other programs running at the same time do not inflate it.', '']
    header = ('| Value | Best fitness (mean ± SD) | Soft (mean ± SD) | Best / worst soft | Hard (mean) | Feasible | '
              'First feasible gen. | Best found at gen. | Final diversity | CPU s |')
    for study, (_, _, title) in STUDIES.items():
        lines += [f'## {title}', '', header, '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
        rows = [s for s in summary if s['study'] == study]
        for s in rows:
            lines.append(f"| {s['label']} | {s['mean_fitness']:.5f} ± {s['sd_fitness']:.5f} | {s['mean_soft']:.1f} ± "
                         f"{s['sd_soft']:.1f} | {s['best_soft']} / {s['worst_soft']} | {s['mean_hard']:.2f} | "
                         f"{s['feasible_rate']:.0%} | {number(s['mean_gen_feasible'], 1)} | {s['mean_gen_best']:.0f} | "
                         f"{s['mean_diversity']:.3f} | {s['mean_runtime']:.2f} |")
        best, worst = min(rows, key=lambda s: s['mean_soft']), max(rows, key=lambda s: s['mean_soft'])
        lines += ['', f"Lowest mean soft penalty: {best['label']} ({best['mean_soft']:.1f}); highest: "
                      f"{worst['label']} ({worst['mean_soft']:.1f}).", '']
    lines += ['## Results table in the format of section 20', '',
              '| Population | Mutation | Crossover | Generations | Best fitness (mean) | Hard violations (mean) | '
              'Soft violations (mean) | CPU s (mean) |', '|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in data['brief_table']:
        lines.append(f"| {r['population']} | {r['mutation']:.0%} | {r['crossover']:.0%} | {r['generations']} | "
                     f"{r['mean_fitness']:.5f} | {r['mean_hard']:.2f} | {r['mean_soft']:.1f} | {r['mean_runtime']:.2f} |")
    lines += ['', '## Number of generations (prefix of the baseline runs)', '',
              'A run with a smaller budget follows exactly the same random sequence, so its result equals the '
              'baseline best-so-far at that generation.', '',
              '| Generations | Fitness evaluations | Best fitness (mean) | Soft (mean) | Hard (mean) |',
              '|---:|---:|---:|---:|---:|']
    for r in data['budgets']:
        lines.append(f"| {r['generations']} | {r['evaluations']} | {r['mean_fitness']:.5f} | {r['mean_soft']:.1f} | "
                     f"{r['mean_hard']:.2f} |")
    lines += ['', '## Advanced D: GA versus hill climbing', '',
              'Hill climbing starts from one random timetable, reassigns one random course per step and keeps the '
              'move if the penalty does not increase. Both methods receive exactly the same number of fitness '
              'evaluations per seed.', '',
              '| Algorithm | Seed | Fitness | Hard | Soft | CPU s | Evaluations | Evaluations to feasible | '
              'Evaluations to best |', '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in data['comparison']:
        lines.append(f"| {r['algorithm']} | {r['seed']} | {r['fitness']:.5f} | {r['hard']} | {r['soft']} | "
                     f"{r['runtime']:.2f} | {r['evaluations']} | {number(r['evals_to_feasible'])} | {r['evals_to_best']} |")
    for name in ('Genetic Algorithm', 'Hill Climbing'):
        group = [r for r in data['comparison'] if r['algorithm'] == name]
        lines.append(f"| **{name} mean** | | {mean(r['fitness'] for r in group):.5f} | "
                     f"{mean(r['hard'] for r in group):.2f} | {mean(r['soft'] for r in group):.1f} | "
                     f"{mean(r['runtime'] for r in group):.2f} | | | {mean(r['evals_to_best'] for r in group):.0f} |")
    lines += ['', '## Figures', '']
    for name, caption in (('convergence.png', 'Generation vs best fitness, representative baseline run'),
                          ('convergence_parameters.png', 'Convergence for population, mutation and crossover'),
                          ('mutation_diversity.png', 'Mutation rate: fitness and population diversity'),
                          ('parameter_studies.png', 'Experiments 1-3: final fitness and runtime'),
                          ('convergence_operators.png', 'Convergence for the operator comparisons'),
                          ('operator_comparison.png', 'Advanced comparisons A-C: final fitness'),
                          ('size_scaling.png', 'Experiment 4: problem size'),
                          ('ga_vs_hill_climbing.png', 'Advanced D: GA versus hill climbing')):
        lines += [f'![{caption}]({name})', '']
    lines += ['## Limits', '',
              f"Measured on one machine with {len(meta['seeds'])} seeds per configuration; runtimes depend on hardware "
              'and load. Error bars and ± values are sample standard deviations, not confidence intervals. Datasets are '
              'synthetic; larger sizes also add instructors and student groups, so the size study measures workload '
              'growth rather than course count alone. Every course has one one-hour weekly meeting. Nothing here '
              'proves optimality.']
    (output / 'REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description='COMP338 experiments: parameter studies, operator comparisons and GA versus hill climbing.')
    parser.add_argument('--generations', type=int, default=500)
    parser.add_argument('--seeds', type=int, nargs='+', default=list(range(1, 11)))
    parser.add_argument('--output', help='output folder (default results/experiments)')
    parser.add_argument('--quick', action='store_true', help='2 seeds x 60 generations, for checking the pipeline')
    parser.add_argument('--render-only', action='store_true', help='rebuild figures and REPORT.md from results.json')
    args = parser.parse_args()
    if args.quick:
        args.generations, args.seeds = 60, [1, 2]
    if args.generations < 1 or len(args.seeds) != len(set(args.seeds)):
        parser.error('Use positive generations and distinct seeds')
    output = Path(args.output or ('results/experiments_quick' if args.quick else 'results/experiments'))
    output.mkdir(parents=True, exist_ok=True)
    if not args.render_only:
        run_suite(args, output)
    render(output)


if __name__ == '__main__':
    main()
