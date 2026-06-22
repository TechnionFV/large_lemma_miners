"""Table and plot builders consumed by get_tables.py.

Each function takes the unified `runs_json` dict (built by `runs_builder`)
and writes outputs to the specified paths.
"""

from __future__ import annotations

import csv
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src"))
)

from models import PAPER_MODEL_SHORTS


# ---------------------------------------------------------------------------
# Tag coarsening (from ablations.py)
# ---------------------------------------------------------------------------

_VIRTUAL_BEST = "__virtual_best__"
_VIRTUAL_BEST_LABEL = "Virtual best"


def _coarse_tag(tag: str) -> str:
    t = (tag or "").lower()
    if "seen" in t or "textbook" in t:
        return "seen"
    if t in {"c, generalize", "c, others"}:
        return "c examples"
    return "others"


# ---------------------------------------------------------------------------
# LaTeX writer for Table 4 (few-shot ablation)
# ---------------------------------------------------------------------------


def write_fewshot_ablation_latex(
    counts,
    tag_totals,
    out_tex: str,
    fewshots: list[int] | None = None,
    existing_cells: set | None = None,
    color: bool = True,
):
    def esc(s: str) -> str:
        repl = {
            "\\": r"\textbackslash{}",
            "&": r"\&",
            "%": r"\%",
            "$": r"\$",
            "#": r"\#",
            "_": r"\_",
            "{": r"\{",
            "}": r"\}",
            "~": r"\textasciitilde{}",
            "^": r"\textasciicircum{}",
        }
        return "".join(repl.get(c, c) for c in str(s))

    def pct(val, tag):
        if not val:
            return ""
        N = tag_totals.get(tag, 0)
        if N == 0:
            return ""
        return f"{100 * val / N:.0f}\\%"

    def cell_color(val, tag):
        if not val:
            return ""
        N = tag_totals.get(tag, 0)
        if N == 0:
            return ""
        p = val / N
        stops = [
            (247, 251, 255),
            (222, 235, 247),
            (198, 219, 239),
            (158, 202, 225),
            (107, 174, 214),
            (66, 146, 198),
            (33, 113, 181),
            (8, 81, 156),
            (8, 48, 107),
        ]
        idx_f = p * (len(stops) - 1)
        lo = int(idx_f)
        hi = min(lo + 1, len(stops) - 1)
        t = idx_f - lo
        r = int(round(stops[lo][0] + t * (stops[hi][0] - stops[lo][0])))
        g = int(round(stops[lo][1] + t * (stops[hi][1] - stops[lo][1])))
        b = int(round(stops[lo][2] + t * (stops[hi][2] - stops[lo][2])))
        text = r"\color{white}" if p > 0.6 else ""
        return r"\cellcolor[RGB]{" + f"{r},{g},{b}" + "}" + text

    models = sorted({m for (m, _mode, _tag) in counts if m != _VIRTUAL_BEST})
    has_virtual_best = any(m == _VIRTUAL_BEST for (m, _mode, _tag) in counts)
    tags = sorted(tag_totals.keys())

    fs_values = list(fewshots) if fewshots is not None else [0, 1, 2]
    fs_cols = tuple(f"few_shot{fs}" for fs in fs_values) + ("all",)
    mode_order = ["agentic", "non_agentic"]

    best: Dict[tuple, int] = {}
    for tag in tags:
        for mode in mode_order:
            for model in models:
                max_val = 0
                for fs in fs_cols:
                    bucket = counts.get((model, mode, tag), {})
                    v = bucket.get(fs, 0)
                    if v > max_val and fs != "all":
                        max_val = v
                if max_val > 0:
                    best[(mode, tag, model)] = max_val

    col_spec = "lll" + ("r" * len(fs_cols)) + "||" + ("r" * len(fs_cols))

    lines = []
    if color:
        lines.append(
            r"% Color palette for percentage cells (paste once per document if reused)."
        )
        lines.append(r"\definecolor{pctred1}{HTML}{F4CCCC}")
        lines.append(r"\definecolor{pctred2}{HTML}{FCD5B4}")
        lines.append(r"\definecolor{pctmid1}{HTML}{FFE599}")
        lines.append(r"\definecolor{pctmid2}{HTML}{FFF2CC}")
        lines.append(r"\definecolor{pctgrn1}{HTML}{E2EFDA}")
        lines.append(r"\definecolor{pctgrn2}{HTML}{C6E0B4}")
        lines.append(r"\definecolor{pctgrn3}{HTML}{A9D08E}")
    lines.append(r"\begin{table*}")
    lines.append(r"\centering")
    lines.append(r"\resizebox{0.9\textwidth}{!}{%")
    lines.append(rf"\begin{{tabular}}{{{col_spec}}}")
    lines.append(r"\toprule")

    header = [
        r"\textbf{Model}",
        r"\textbf{Tag}",
        r"\textbf{Total}",
        rf"\multicolumn{{{len(fs_cols)}}}{{c}}{{Agentic}}",
        rf"\multicolumn{{{len(fs_cols)}}}{{c}}{{Non-agentic}}",
    ]
    lines.append(" & ".join(header) + r" \\")

    sub = ["", "", ""]
    for _mode in mode_order:
        for fs in fs_cols:
            sub.append("FS=" + fs.replace("few_shot", ""))
    lines.append(" & ".join(sub) + r" \\")
    lines.append(r"\midrule")

    for model in models:
        n_tag_rows = len(tags)
        for j, tag in enumerate(tags):
            if j == 0 and n_tag_rows > 1:
                model_cell = rf"\multirow{{{n_tag_rows}}}{{*}}{{{esc(model)}}}"
            elif n_tag_rows == 1:
                model_cell = esc(model)
            else:
                model_cell = ""

            row = [model_cell, esc(tag), str(tag_totals.get(tag, ""))]

            for mode in mode_order:
                bucket = counts.get((model, mode, tag), {})
                for fs in fs_cols:
                    raw_val = bucket.get(fs, 0)
                    cell = pct(raw_val, tag)

                    if existing_cells is not None:
                        if fs == "all":
                            has_any = any(
                                (model, mode, f) in existing_cells for f in fs_values
                            )
                            missing = not has_any
                        else:
                            fs_int = int(fs.replace("few_shot", ""))
                            missing = (model, mode, fs_int) not in existing_cells
                        if missing:
                            cell = r"$\ast$"

                    if (
                        cell
                        and not cell.startswith("$")
                        and best.get((mode, tag, model)) == raw_val
                        and fs != "all"
                    ):
                        cell = r"\textbf{" + cell + "}"

                    if color and cell and not cell.startswith("$"):
                        cell = cell_color(raw_val, tag) + cell

                    row.append(cell)

            lines.append(" & ".join(row) + r" \\")
        lines.append(r"\midrule")

    if has_virtual_best:
        n_tag_rows = len(tags)
        for j, tag in enumerate(tags):
            if j == 0 and n_tag_rows > 1:
                vb_cell = (
                    rf"\multirow{{{n_tag_rows}}}{{*}}"
                    rf"{{\textbf{{{esc(_VIRTUAL_BEST_LABEL)}}}}}"
                )
            elif n_tag_rows == 1:
                vb_cell = r"\textbf{" + esc(_VIRTUAL_BEST_LABEL) + "}"
            else:
                vb_cell = ""
            row = [
                vb_cell,
                esc(tag),
                str(tag_totals.get(tag, "")),
            ]
            for mode in mode_order:
                bucket = counts.get((_VIRTUAL_BEST, mode, tag), {})
                for fs in fs_cols:
                    raw_val = bucket.get(fs, 0)
                    cell = pct(raw_val, tag)

                    if existing_cells is not None:
                        if fs == "all":
                            has_any = any(
                                (m, mode, f) in existing_cells
                                for m in models
                                for f in fs_values
                            )
                            missing = not has_any
                        else:
                            fs_int = int(fs.replace("few_shot", ""))
                            missing = not any(
                                (m, mode, fs_int) in existing_cells for m in models
                            )
                        if missing:
                            cell = r"$\ast$"

                    if color and cell and not cell.startswith("$"):
                        cell = cell_color(raw_val, tag) + cell

                    row.append(cell)
            lines.append(" & ".join(row) + r" \\")

    lines.append(r"\bottomrule")
    lines.append(r"\end{tabular}")
    lines.append(r"}")
    lines.append(r"\caption{Few-shot ablation results, extended}")
    lines.append(r"\label{tab:fewshot-ablation}")
    lines.append(r"\end{table*}")

    with open(out_tex, "w") as f:
        f.write("\n".join(lines))

    print(f"[OK] LaTeX written to {out_tex}")


# ---------------------------------------------------------------------------
# LaTeX renderer for Table 2 (hard-benchmark runtime comparison)
# ---------------------------------------------------------------------------

_TIMEOUT_UNSOLVED = "@@TIMEOUT@@"
_TIMEOUT_SLOW = "@@TIMEOUT_SLOW@@"
_RAW_LATEX = {
    _TIMEOUT_UNSOLVED: r"TIMEOUT",
    _TIMEOUT_SLOW: r"TIMEOUT$^\dagger$",
}


def _escape_latex(s: str) -> str:
    return (
        s.replace("\\", r"\textbackslash{}")
        .replace("&", r"\&")
        .replace("%", r"\%")
        .replace("$", r"\$")
        .replace("#", r"\#")
        .replace("_", r"\_")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("~", r"\textasciitilde{}")
        .replace("^", r"\textasciicircum{}")
    )


def _emit_cell(cell: str) -> str:
    if cell in _RAW_LATEX:
        return _RAW_LATEX[cell]
    return _escape_latex(cell)


def _fmt(x):
    if x is None:
        return "unsolved"
    if x == "TIMEOUT":
        return "TIMEOUT"
    if isinstance(x, (int, float)):
        return f"{x:.2f}"
    return str(x)


def _vcf_seconds(s: str) -> float | None:
    s = s.strip()
    if not s:
        return None
    low = s.lower()
    if "more than" in low or "24h" in low.replace(" ", ""):
        return float("inf")
    if ":" in s:
        try:
            parts = [float(p) for p in s.split(":")]
        except ValueError:
            return None
        if len(parts) == 3:
            h, m, sec = parts
            return h * 3600 + m * 60 + sec
        if len(parts) == 2:
            m, sec = parts
            return m * 60 + sec
        return None
    try:
        return float(s)
    except ValueError:
        return None


def json_to_latex_table(
    json_path: str,
    tags_path: str,
    caption: str = "Runtime comparison (in seconds)",
    label: str = "tab:hard_benchmarks",
) -> str:
    data = json.loads(Path(json_path).read_text())
    tags = json.loads(Path(tags_path).read_text()) if tags_path else {}

    rows = []
    for design, obj in data.items():
        if not isinstance(obj, dict):
            continue
        tag = tags.get(design, "")
        if tag == "":
            print(f"[WARNING] No tag for {design}")
            continue

        vb_raw = obj.get("virtual_best")
        if vb_raw is None:
            vb = _TIMEOUT_UNSOLVED
        elif isinstance(vb_raw, (int, float)):
            if vb_raw > 3600:
                print(
                    f"design {design} took {vb_raw:.2f} seconds (>3600); marking TIMEOUT†"
                )
                vb = _TIMEOUT_SLOW
            else:
                vb = f"{vb_raw:.2f}"
        else:
            vb = _fmt(vb_raw)

        ric3_cell = ""
        ric3 = obj.get("ric3")
        if isinstance(ric3, dict):
            err = ric3.get("error")
            t = ric3.get("time")
            if err == "timeout":
                assert t is None
                ric3_cell = "TIMEOUT"
            elif err is None:
                ric3_cell = _fmt(t)

        jasper_cell = ""
        jasper = obj.get("jasper")
        if isinstance(jasper, dict):
            err = jasper.get("error")
            t = jasper.get("time")
            if err == "CEX":
                print(f"[WARNING] JasperGold refuted {design}")
                continue
            if err is not None:
                print(f"[WARNING] JasperGold error for {design}: {err}")
            else:
                jasper_cell = _fmt(t)

        vcf_raw = obj.get("vcf_time")
        if vcf_raw is None or vcf_raw == "":
            vcf_cell = ""
        elif vcf_raw == "TIMEOUT":
            vcf_cell = "TIMEOUT"
        elif isinstance(vcf_raw, (int, float)):
            vcf_cell = "TIMEOUT" if vcf_raw > 3600 else f"{vcf_raw:.2f}"
        else:
            secs = _vcf_seconds(str(vcf_raw))
            if secs is None:
                vcf_cell = str(vcf_raw)
            elif secs > 3600:
                vcf_cell = "TIMEOUT"
            else:
                vcf_cell = f"{secs:.2f}"

        if (
            vb in ("", _TIMEOUT_UNSOLVED)
            and ric3_cell == ""
            and jasper_cell == ""
            and vcf_cell == ""
        ):
            print(f"[WARNING] No data for {design}, skipping")
            continue

        rows.append((tag, design, vb, ric3_cell, jasper_cell, vcf_cell))

    rows.sort(key=lambda x: (x[0], x[1]))

    out = []
    out.append(r"\begin{table*}[t]")
    out.append(r"\centering")
    out.append(r"\begin{tabular}{llrrrr}")
    out.append(r"\toprule")
    out.append(r"Category & Design & Our virtual best & rIC3 & JasperGold & VCF \\")
    out.append(r"\midrule")

    tag_rows = []
    i = 0
    while i < len(rows):
        tag = rows[i][0]
        group_start = i
        while i < len(rows) and rows[i][0] == tag:
            i += 1
        group_size = i - group_start
        tag_rows.append((tag, group_size, group_start))

    for idx, (tag, count, start_idx) in enumerate(tag_rows):
        if idx > 0:
            out.append(r"\cmidrule{1-6}")

        for j in range(count):
            _, design, vb, ric3, jasper, vcf = rows[start_idx + j]
            if j == 0:
                tag_cell = (
                    f"\\multirow{{{count}}}{{*}}{{{_escape_latex(tag)}}}"
                    if count > 1
                    else _escape_latex(tag)
                )
            else:
                tag_cell = ""
            out.append(
                f"{tag_cell} & "
                f"{_emit_cell(design)} & "
                f"{_emit_cell(vb)} & "
                f"{_emit_cell(ric3)} & "
                f"{_emit_cell(jasper)} & "
                f"{_emit_cell(vcf)} \\\\"
            )

    out.append(r"\bottomrule")
    out.append(r"\end{tabular}")
    out.append(rf"\caption{{{_escape_latex(caption)}}}")
    out.append(rf"\label{{{_escape_latex(label)}}}")
    out.append(r"\end{table*}")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Module iteration and filtering
# ---------------------------------------------------------------------------


def _iter_modules(runs_json: dict):
    for k, v in runs_json.items():
        if k.startswith("_"):
            continue
        yield k, v


def filter_runs(
    runs_json: dict,
    *,
    agent_num_iterations: int | list[int] | None = None,
    non_agent_num_samples: int | list[int] | None = None,
    fewshots: list[int] | None = None,
) -> dict:
    """Return a shallow-copied `runs_json` keeping only runs that match ALL
    specified criteria. Arguments set to None disable that filter axis."""
    iter_set = (
        None
        if agent_num_iterations is None
        else {agent_num_iterations}
        if isinstance(agent_num_iterations, int)
        else set(agent_num_iterations)
    )
    ns_set = (
        None
        if non_agent_num_samples is None
        else {non_agent_num_samples}
        if isinstance(non_agent_num_samples, int)
        else set(non_agent_num_samples)
    )
    fs_set = None if fewshots is None else set(fewshots)

    def _run_ok(run: dict) -> bool:
        if fs_set is not None and run["fewshot"] not in fs_set:
            return False
        if run["pipeline"] == "agent":
            if iter_set is not None and run.get("num_iterations") not in iter_set:
                return False
        else:
            if ns_set is not None and run.get("num_samples") not in ns_set:
                return False
        return True

    def _totals_ok(totals: dict) -> bool:
        if fs_set is not None and totals["fewshot"] not in fs_set:
            return False
        if totals["pipeline"] == "agent":
            if iter_set is not None and totals.get("num_iterations") not in iter_set:
                return False
        else:
            if ns_set is not None and totals.get("num_samples") not in ns_set:
                return False
        return True

    result: dict = {}
    for k, v in runs_json.items():
        if k == "_generated_from":
            result[k] = v
        elif k == "_run_totals":
            result[k] = {rk: tot for rk, tot in v.items() if _totals_ok(tot)}
        else:
            filtered_runs = {rk: run for rk, run in v["runs"].items() if _run_ok(run)}
            result[k] = {"metadata": v["metadata"], "runs": filtered_runs}
    return result


# ---------------------------------------------------------------------------
# Table 1 — overall by model x (agentic / non-agentic)
# ---------------------------------------------------------------------------


def _format_console_table(headers, rows):
    widths = [
        max(len(str(h)), *(len(str(r[i])) for r in rows)) for i, h in enumerate(headers)
    ]

    def fmt(r):
        return " | ".join(str(c).ljust(widths[i]) for i, c in enumerate(r))

    sep = "-+-".join("-" * w for w in widths)
    return "\n".join([fmt(headers), sep] + [fmt(r) for r in rows])


def _write_latex_overall_paired(
    path,
    *,
    models_order,
    rows_by_model,
    vb_agentic_solved,
    vb_nonagentic_solved,
    caption,
    label="tab:overall",
):
    def esc(s):
        return (
            str(s)
            .replace("\\", "\\textbackslash{}")
            .replace("&", "\\&")
            .replace("%", "\\%")
            .replace("_", "\\_")
            .replace("#", "\\#")
            .replace("{", "\\{")
            .replace("}", "\\}")
            .replace("^", "\\^{}")
            .replace("~", "\\textasciitilde{}")
            .replace("$", "\\$")
        )

    col_spec = "@{}lrrrrrrrrrrr@{}"
    lines = []
    lines += [
        r"\begin{table*}[t]",
        r"  \centering",
        r"  \scalebox{0.95}{",
        f"  \\begin{{tabular}}{{{col_spec}}}",
        r"    \toprule",
        r"    & \multicolumn{5}{c}{Agentic} & \multicolumn{5}{c}{Non-Agentic} \\",
        r"    \cmidrule(lr){2-6}\cmidrule(lr){7-11}",
        r"    Model & Total Lemmas & Correct & 1-Inductive & Error & Solved & Total Lemmas & Correct & 1-Inductive & Error & Solved \\",
        r"    \midrule",
    ]
    for m in models_order:
        row = rows_by_model.get(m, [""] * 10)
        row_str = " & ".join("" if x == "" else str(x) for x in row)
        lines.append(f"    {esc(m)} & {row_str} \\\\")
    lines.append(r"    \addlinespace")
    vb_cells = ["", "", "", "", vb_agentic_solved, "", "", "", "", vb_nonagentic_solved]
    vb_str = " & ".join("" if x == "" else str(x) for x in vb_cells)
    lines.append(f"    Virtual best & {vb_str} \\\\")
    lines += [
        r"    \bottomrule",
        r"  \end{tabular}",
        r"             }",
        f"  \\caption{{{esc(caption)}}}",
        f"  \\label{{{esc(label)}}}",
        r"\end{table*}",
    ]
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def build_table1_from_runs(runs_json: dict, out_dir: Path) -> dict:
    """Paper Table 1: overall results by model and pipeline.

    Writes: `out_dir/overall_from_experiments.{tex,csv}`.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    run_totals = runs_json.get("_run_totals", {})
    desired_order = list(PAPER_MODEL_SHORTS)

    lemma: Dict[tuple, Dict[str, int]] = defaultdict(
        lambda: {"total_lemmas": 0, "correct": 0, "one_inductive": 0, "error": 0}
    )
    for _rk, tot in run_totals.items():
        key = (tot["model"], tot["pipeline"])
        for k in ("total_lemmas", "correct", "one_inductive", "error"):
            lemma[key][k] += tot.get(k, 0)

    solved_sets: Dict[tuple, set] = defaultdict(set)
    for module, entry in _iter_modules(runs_json):
        for _rk, run in entry["runs"].items():
            if run["status"] == "Solved":
                solved_sets[(run["model"], run["pipeline"])].add(module)

    vb_agentic = len(
        {
            module
            for module, entry in _iter_modules(runs_json)
            for run in entry["runs"].values()
            if run["pipeline"] == "agent" and run["status"] == "Solved"
        }
    )
    vb_nonagentic = len(
        {
            module
            for module, entry in _iter_modules(runs_json)
            for run in entry["runs"].values()
            if run["pipeline"] == "non_agent" and run["status"] == "Solved"
        }
    )

    models_seen = {m for (m, _p) in lemma} | {m for (m, _p) in solved_sets}
    models_order = [m for m in desired_order if m in models_seen]
    assert len(models_order) == len(desired_order), (
        f"Missing models: expected {desired_order}, found {sorted(models_seen)}"
    )

    rows_by_model: Dict[str, list] = {}
    for m in models_order:
        a = lemma[(m, "agent")]
        n = lemma[(m, "non_agent")]
        rows_by_model[m] = [
            a["total_lemmas"],
            a["correct"],
            a["one_inductive"],
            a["error"],
            len(solved_sets[(m, "agent")]),
            n["total_lemmas"],
            n["correct"],
            n["one_inductive"],
            n["error"],
            len(solved_sets[(m, "non_agent")]),
        ]

    headers = [
        "Model",
        "A: Total Lemmas",
        "A: Correct",
        "A: 1-Inductive",
        "A: Error",
        "A: Solved",
        "N: Total Lemmas",
        "N: Correct",
        "N: 1-Inductive",
        "N: Error",
        "N: Solved",
    ]
    rows_overall = [[m] + rows_by_model[m] for m in models_order]
    vb_label = "Virtual best"

    print("\n=== Overall (by model; Agentic/Non-Agentic groups) ===")
    print(
        _format_console_table(
            headers,
            rows_overall
            + [[vb_label, "", "", "", "", vb_agentic, "", "", "", "", vb_nonagentic]],
        )
    )

    csv_path = out_dir / "overall_from_experiments.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows_overall)
        w.writerow(
            [vb_label, "", "", "", "", vb_agentic, "", "", "", "", vb_nonagentic]
        )

    tex_path = out_dir / "overall_from_experiments.tex"
    _write_latex_overall_paired(
        tex_path,
        models_order=models_order,
        rows_by_model=rows_by_model,
        vb_agentic_solved=vb_agentic,
        vb_nonagentic_solved=vb_nonagentic,
        caption="Overall results by model and setup",
    )

    return {
        "headers": headers,
        "rows": rows_overall,
        "models_order": models_order,
        "rows_by_model": rows_by_model,
        "vb_agentic": vb_agentic,
        "vb_nonagentic": vb_nonagentic,
    }


# ---------------------------------------------------------------------------
# Table 2 — hard-benchmark runtime comparison
# ---------------------------------------------------------------------------


def build_table2_from_runs(
    runs_json: dict,
    out_dir: Path,
    sota_timings_dir: Path,
    hard_tags_path: Path,
    fewshot_variants: list[tuple[list[int], str]] | None = None,
) -> None:
    """Paper Table 2: timing comparison on hard benchmarks.

    Writes: `out_dir/timings_hard_<variant>.{tex,json}` for each variant.
    """
    if fewshot_variants is None:
        fewshot_variants = [
            ([0, 1, 2], "all"),
            ([1], "fs1"),
            ([0], "fs0"),
            ([2], "fs2"),
        ]

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    hard_tags = json.loads(Path(hard_tags_path).read_text())

    sota_timings_dir = Path(sota_timings_dir)
    ric3 = json.loads((sota_timings_dir / "ric3.json").read_text())
    jasper = json.loads((sota_timings_dir / "jasper.json").read_text())
    vcf = json.loads((sota_timings_dir / "vcf.json").read_text())

    for fewshots, name_id in fewshot_variants:
        per_module: Dict[str, dict] = {}
        for module, entry in _iter_modules(runs_json):
            if module not in hard_tags:
                continue

            solving_runs = [
                r
                for r in entry["runs"].values()
                if r["fewshot"] in fewshots
                and r["status"] == "Solved"
                and r.get("total_time") is not None
            ]
            n = len(solving_runs)
            if n == 0:
                per_module[module] = {
                    "n_settings": 0,
                    "avg_inference_time": None,
                    "avg_evaluation_time": None,
                    "avg_total_time": None,
                    "avg_tokens": None,
                    "virtual_best": None,
                }
                continue

            def _avg(runs, field):
                vals = [r[field] for r in runs if r.get(field) is not None]
                return (sum(vals) / len(vals)) if vals else None

            per_module[module] = {
                "n_settings": n,
                "avg_inference_time": _avg(solving_runs, "inference_time"),
                "avg_evaluation_time": _avg(solving_runs, "evaluation_time"),
                "avg_total_time": _avg(solving_runs, "total_time"),
                "avg_tokens": _avg(solving_runs, "tokens"),
                "virtual_best": min(r["total_time"] for r in solving_runs),
            }

        for module, rec in per_module.items():
            if module in ric3:
                rec["ric3"] = ric3[module]
            if module in jasper:
                rec["jasper"] = jasper[module]
            if module in vcf:
                v = vcf[module]
                rec["vcf_time"] = (
                    "TIMEOUT"
                    if isinstance(v, str) and v.lower().startswith("timeout")
                    else v
                )

        json_path = out_dir / f"timings_hard_{name_id}.json"
        with open(json_path, "w") as f:
            json.dump(per_module, f, indent=2, sort_keys=True)

        tex_path = out_dir / f"timings_hard_{name_id}.tex"
        tex = json_to_latex_table(
            json_path=str(json_path), tags_path=str(hard_tags_path)
        )
        tex_path.write_text(tex)
        print(f"[INFO] Wrote LaTeX table to {tex_path.name}")


# ---------------------------------------------------------------------------
# Table 3 — solved/unsolved by category
# ---------------------------------------------------------------------------


def _latex_category_table(
    solved_counts: Dict[str, int], unsolved_counts: Dict[str, int]
) -> str:
    all_tags = sorted(set(solved_counts.keys()) | set(unsolved_counts.keys()))
    lines = [
        "\\begin{table}[h]",
        "\\centering",
        "\\scalebox{0.99}{",
        "\\begin{tabular}{l rr}",
        "\\toprule",
        "Group Tag & Solved & Unsolved \\\\",
        "\\midrule",
    ]
    for tag in all_tags:
        lines.append(
            f"{tag} & {solved_counts.get(tag, 0)} & {unsolved_counts.get(tag, 0)} \\\\"
        )
    lines += [
        "\\midrule",
        f"Total & {sum(solved_counts.values())} & {sum(unsolved_counts.values())} \\\\",
        "\\bottomrule",
        "\\end{tabular}",
        "}",
        "\\caption{Solved vs.~unsolved examples by category}",
        "\\label{tab:solved_unsolved_groups}",
        "\\end{table}",
    ]
    return "\n".join(lines)


def build_table3_from_runs(
    runs_json: dict,
    out_path: Path,
    fewshots: list[int] | None = None,
    pipelines: list[str] | None = None,
) -> None:
    """Paper Table 3: solved/unsolved counts grouped by benchmark category."""
    solved_counts: Dict[str, int] = defaultdict(int)
    unsolved_counts: Dict[str, int] = defaultdict(int)

    unsolved_list: list = []
    for module, entry in _iter_modules(runs_json):
        tag = entry["metadata"]["tag"]
        relevant_runs = []
        for run in entry["runs"].values():
            if fewshots is not None and run["fewshot"] not in fewshots:
                continue
            if pipelines is not None and run["pipeline"] not in pipelines:
                continue
            relevant_runs.append(run)

        if any(r["status"] == "Solved" for r in relevant_runs):
            solved_counts[tag] += 1
        else:
            unsolved_counts[tag] += 1
            unsolved_list.append({"module": module, "tag": tag})

    print(f"modules that were not solved by any setting: {unsolved_list}")
    print(f"counts: {dict(solved_counts)}")
    print(f"counts: {dict(unsolved_counts)}")

    table_str = _latex_category_table(solved_counts, unsolved_counts)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(table_str, encoding="utf-8")
    print(f"LaTeX table written to {out_path}")


# ---------------------------------------------------------------------------
# Table 4 — few-shot ablation
# ---------------------------------------------------------------------------


def build_table4_from_runs(
    runs_json: dict,
    out_tex: Path | None,
    coarse_out_tex: Path,
    fewshots: list[int] | None = None,
) -> None:
    """Paper Table 4: few-shot ablation (coarse-tag breakdown).

    Pass `out_tex=None` to skip the fine-grained table.
    """
    fs_values = list(fewshots) if fewshots is not None else [0, 1, 2]

    _MODE = {"agent": "agentic", "non_agent": "non_agentic"}

    existing_cells: set = set()
    for _rk, tot in runs_json.get("_run_totals", {}).items():
        if tot["fewshot"] in fs_values:
            existing_cells.add((tot["model"], _MODE[tot["pipeline"]], tot["fewshot"]))

    tag_totals: Dict[str, int] = defaultdict(int)
    for _module, entry in _iter_modules(runs_json):
        tag_totals[entry["metadata"]["tag"]] += 1

    coarse_totals: Dict[str, int] = defaultdict(int)
    for tag, cnt in tag_totals.items():
        coarse_totals[_coarse_tag(tag)] += cnt

    counts: Dict[tuple, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    coarse_counts: Dict[tuple, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    vb_seen_modules: Dict[tuple, set[str]] = defaultdict(set)
    vb_seen_modules_coarse: Dict[tuple, set[str]] = defaultdict(set)

    for module, entry in _iter_modules(runs_json):
        tag = entry["metadata"]["tag"]
        coarse = _coarse_tag(tag)

        per_fs: Dict[tuple, bool] = defaultdict(bool)
        for run in entry["runs"].values():
            if run["status"] != "Solved":
                continue
            if run["fewshot"] not in fs_values:
                continue
            per_fs[(run["model"], run["pipeline"], run["fewshot"])] = True

        for (model, pipeline, fs), solved in per_fs.items():
            if solved:
                fs_col = f"few_shot{fs}"
                mode = _MODE[pipeline]
                counts[(model, mode, tag)][fs_col] += 1
                coarse_counts[(model, mode, coarse)][fs_col] += 1
                vb_seen_modules[(mode, tag, fs_col)].add(module)
                vb_seen_modules_coarse[(mode, coarse, fs_col)].add(module)

        per_pair: Dict[tuple, bool] = defaultdict(bool)
        for (model, pipeline, _fs), solved in per_fs.items():
            per_pair[(model, pipeline)] |= solved
        for (model, pipeline), solved in per_pair.items():
            if solved:
                mode = _MODE[pipeline]
                counts[(model, mode, tag)]["all"] += 1
                coarse_counts[(model, mode, coarse)]["all"] += 1
                vb_seen_modules[(mode, tag, "all")].add(module)
                vb_seen_modules_coarse[(mode, coarse, "all")].add(module)

    for (mode, tag, fs_col), mods in vb_seen_modules.items():
        counts[(_VIRTUAL_BEST, mode, tag)][fs_col] = len(mods)
    for (mode, coarse, fs_col), mods in vb_seen_modules_coarse.items():
        coarse_counts[(_VIRTUAL_BEST, mode, coarse)][fs_col] = len(mods)

    total_modules = sum(tag_totals.values())
    by_fs_agent: Dict[int, set[str]] = defaultdict(set)
    by_fs_non: Dict[int, set[str]] = defaultdict(set)
    any_fs_agent: set[str] = set()
    any_fs_non: set[str] = set()
    for module, entry in _iter_modules(runs_json):
        for run in entry["runs"].values():
            if run["status"] != "Solved":
                continue
            if run["fewshot"] not in fs_values:
                continue
            if run["pipeline"] == "agent":
                by_fs_agent[run["fewshot"]].add(module)
                any_fs_agent.add(module)
            elif run["pipeline"] == "non_agent":
                by_fs_non[run["fewshot"]].add(module)
                any_fs_non.add(module)

    def _pct(n: int) -> str:
        if total_modules == 0:
            return "n/a"
        return f"{100 * n / total_modules:.1f}%"

    def _fmt(n: int) -> str:
        return f"{n:>3} ({_pct(n):>6})"

    print("\n=== Virtual best per fewshot (across all models) ===")
    print(f"{'FS':>4}  {'Agentic':>12}  {'Non-Agentic':>12}  {'Combined':>12}  Total")
    for fs in fs_values:
        a = by_fs_agent[fs]
        n = by_fs_non[fs]
        c = a | n
        print(
            f"{fs:>4}  {_fmt(len(a))}  {_fmt(len(n))}  {_fmt(len(c))}  {total_modules}"
        )
    a_any = any_fs_agent
    n_any = any_fs_non
    c_any = a_any | n_any
    print(
        f"{'any':>4}  {_fmt(len(a_any))}  {_fmt(len(n_any))}  {_fmt(len(c_any))}  {total_modules}"
    )

    if out_tex is not None:
        write_fewshot_ablation_latex(
            counts,
            dict(tag_totals),
            str(out_tex),
            fewshots=fs_values,
            existing_cells=existing_cells,
        )
        print(f"[OK] Wrote fine table   -> {out_tex}")
    write_fewshot_ablation_latex(
        coarse_counts,
        dict(coarse_totals),
        str(coarse_out_tex),
        fewshots=fs_values,
        existing_cells=existing_cells,
    )
    print(f"[OK] Wrote coarse table -> {coarse_out_tex}")


# ---------------------------------------------------------------------------
# Num-iterations ablation — line plot
# ---------------------------------------------------------------------------


def build_num_iterations_ablation_plots(
    runs_json: dict,
    *,
    ks: list[int],
    non_agent_num_samples: int | None,
    out_dir: Path,
) -> None:
    """Emit line plot: % modules solved vs K, virtual best lines per model/fewshot/overall."""
    import matplotlib.pyplot as plt

    ks_sorted = sorted(set(ks))

    total_modules = sum(1 for _ in _iter_modules(runs_json))

    seen_pairs: set[tuple[str, int]] = set()
    for _module, entry in _iter_modules(runs_json):
        for run in entry["runs"].values():
            if run["pipeline"] == "agent":
                seen_pairs.add((run["model"], run["fewshot"]))

    solved_at: dict[tuple[str, int, int], set[str]] = defaultdict(set)
    for module, entry in _iter_modules(runs_json):
        for run in entry["runs"].values():
            if run["pipeline"] == "agent" and run["status"] == "Solved":
                k = run.get("num_iterations")
                if k in ks_sorted:
                    solved_at[(run["model"], run["fewshot"], k)].add(module)

    models_seen = sorted(set(m for m, _fs in seen_pairs))
    fewshots_seen = sorted(set(fs for _m, fs in seen_pairs))

    model_order = [m for m in PAPER_MODEL_SHORTS if m in models_seen]
    model_order += [m for m in models_seen if m not in model_order]

    cumulative_solved: dict[tuple[str, int, int], set[str]] = {}
    for model in model_order:
        for fs in fewshots_seen:
            running = set()
            for k in ks_sorted:
                running = running | solved_at.get((model, fs, k), set())
                cumulative_solved[(model, fs, k)] = set(running)

    vb_per_model: dict[tuple[str, int], set[str]] = {}
    for model in model_order:
        for k in ks_sorted:
            union = set()
            for fs in fewshots_seen:
                union |= cumulative_solved.get((model, fs, k), set())
            vb_per_model[(model, k)] = union

    vb_per_fs: dict[tuple[int, int], set[str]] = {}
    for fs in fewshots_seen:
        for k in ks_sorted:
            union = set()
            for model in model_order:
                union |= cumulative_solved.get((model, fs, k), set())
            vb_per_fs[(fs, k)] = union

    vb_overall: dict[int, set[str]] = {}
    for k in ks_sorted:
        union = set()
        for model in model_order:
            for fs in fewshots_seen:
                union |= cumulative_solved.get((model, fs, k), set())
        vb_overall[k] = union

    def pct(s):
        return 100.0 * len(s) / total_modules if total_modules > 0 else 0.0

    plt.rcParams.update({"font.size": 18})
    fig, ax = plt.subplots(figsize=(12, 6))

    import matplotlib.cm as cm

    model_colors = {}
    cmap = cm.get_cmap("tab10", len(model_order))
    for i, model in enumerate(model_order):
        model_colors[model] = cmap(i)

    for model in model_order:
        y = [pct(vb_per_model[(model, k)]) for k in ks_sorted]
        if max(y) == 0:
            continue
        ax.plot(
            ks_sorted,
            y,
            marker="^",
            markersize=5,
            linewidth=2,
            color=model_colors[model],
            linestyle="-",
            label=f"VB {model}",
        )

    gray_shades = ["#444444", "#666666", "#888888", "#AAAAAA", "#CCCCCC"]
    for fi, fs in enumerate(fewshots_seen):
        y = [pct(vb_per_fs[(fs, k)]) for k in ks_sorted]
        if max(y) == 0:
            continue
        ax.plot(
            ks_sorted,
            y,
            marker="s",
            markersize=4,
            linewidth=2,
            color=gray_shades[fi % len(gray_shades)],
            linestyle=":",
            label=f"VB k={fs}",
        )

    y = [pct(vb_overall[k]) for k in ks_sorted]
    ax.plot(
        ks_sorted,
        y,
        marker="D",
        markersize=6,
        linewidth=2.5,
        linestyle="--",
        color="black",
        label="VB overall",
    )

    ax.set_xlabel("Number of iterations (n)")
    ax.set_ylabel(f"% examples solved (out of {total_modules})")
    ax.set_xticks(ks_sorted)
    ax.margins(y=0.05)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="lower right", ncol=2)

    fig.tight_layout()
    out_line = out_dir / "num_iterations_ablation_line.png"
    fig.savefig(out_line, dpi=150)
    plt.close(fig)
    print(f"[OK] Wrote line plot -> {out_line}")
