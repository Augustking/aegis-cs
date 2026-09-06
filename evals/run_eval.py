# -*- coding: utf-8 -*-
"""
Aegis-CS 评测脚本（需在项目根目录、已配置 .env 后运行）
  python evals/run_eval.py classify : 意图分类准确率（30 题，六桶）
  python evals/run_eval.py gate     : 业务链路真实运行，采集质检分数/延迟/调用次数（可断点续跑）
  python evals/run_eval.py bad      : 质检坏例拦截率（10 条构造坏例）
  python evals/run_eval.py report   : 阈值扫描曲线 + 汇总报告（离线）

指标口径：
  误拦率 FPR = 正常业务问题被判低于阈值转人工的比例（good 集上逐阈值计算）
  拦截率 TPR = 构造坏例被判低于阈值转人工的比例（bad 集上逐阈值计算）
"""
import argparse
import json
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault(
    "TICKET_DB_PATH", os.path.join(ROOT, "evals", "results", "eval_tickets.db")
)

import multi_agent_customer_service as svc  # noqa: E402
from tools import build_judge_messages, classify_query, parse_judge_output  # noqa: E402

RESULTS = os.path.join(ROOT, "evals", "results")
SET_PATH = os.path.join(ROOT, "evals", "eval_set.json")
CLS_CACHE = os.path.join(RESULTS, "cls_cache.json")
GATE_CACHE = os.path.join(RESULTS, "gate_cache.json")
BAD_CACHE = os.path.join(RESULTS, "bad_cache.json")


def load_set():
    with open(SET_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_json(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def stage_classify(llm, data):
    """意图分类准确率"""
    cache = load_json(CLS_CACHE, {})
    items = [(it, b["label"]) for b in data["buckets"] for it in b["items"]]
    for idx, (q, expected) in enumerate(items):
        if q in cache:
            continue
        pred = classify_query.invoke({"query": q, "llm": llm})
        cache[q] = {"expected": expected, "predicted": pred}
        save_json(CLS_CACHE, cache)
        print(f"[classify {idx + 1}/{len(items)}] {q[:18]}… -> {pred}")
    correct = sum(1 for v in cache.values() if v["expected"] == v["predicted"])
    total = len(cache)
    print(f"\n分类准确率: {correct}/{total} = {correct / total:.1%}")
    per = {}
    for q, v in cache.items():
        b = per.setdefault(v["expected"], [0, 0])
        b[1] += 1
        b[0] += v["expected"] == v["predicted"]
    for k, (c, t) in sorted(per.items()):
        print(f"  {k:18s} {c}/{t}")


def stage_gate(llm, data, workers=None):
    """真实图运行：采集质检分数 / 误拦 / 延迟 / 调用次数（断点续跑）
    默认串行：延迟指标必须反映单会话真实体验；并发会触发免费档限速、污染延迟数字。"""
    from concurrent.futures import ThreadPoolExecutor

    if workers is None:
        workers = int(os.getenv("GATE_WORKERS", "1"))

    cache = load_json(GATE_CACHE, {})
    in_scope = [
        (it, b["label"])
        for b in data["buckets"]
        if b["label"] != "out_of_scope"
        for it in b["items"]
    ]
    todo = [(idx, q, bucket) for idx, (q, bucket) in enumerate(in_scope) if q not in cache]
    app = svc.make_graph()

    def run_one(item):
        idx, q, bucket = item
        t0 = time.time()
        state = app.invoke({"customer_query": q, "session_id": f"eval-gate-{idx}"})
        dt = time.time() - t0
        trace = state.get("decision_trace") or []
        qstep = next((s for s in trace if s.get("step") == "quality_check"), None)
        return q, {
            "bucket": bucket,
            "latency_s": round(dt, 2),
            "query_type": state.get("query_type"),
            "needs_human": bool(state.get("needs_human")),
            "quality_score": (qstep or {}).get("score"),
            "quality_reason": (qstep or {}).get("reason"),
            "llm_calls": (1 if any(s.get("step") == "classify" for s in trace) else 0)
            + (2 if any(s.get("step") == "quality_check" for s in trace) else 0),
            "reply_head": str(state.get("response", ""))[:60],
        }

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for q, rec in pool.map(run_one, todo):
            cache[q] = rec
            save_json(GATE_CACHE, cache)
            print(
                f"[gate {len(cache)}/{len(in_scope)}] {q[:16]}… score={rec['quality_score']} "
                f"handoff={rec['needs_human']} calls={rec['llm_calls']} {rec['latency_s']}s",
                flush=True,
            )
    print(f"\ngate 完成，共 {len(cache)} 条（缓存于 {GATE_CACHE}）")


def stage_bad(llm, data):
    """构造坏例的质检打分（断点续跑）"""
    out = load_json(BAD_CACHE, [])
    for idx, bc in enumerate(data["bad_cases"]):
        if any(x["question"] == bc["question"] and x["flaw"] == bc["flaw"] for x in out):
            continue
        resp = llm.invoke(build_judge_messages(bc["question"], bc["reply"]))
        score, reason = parse_judge_output(getattr(resp, "content", ""))
        out.append(
            {"question": bc["question"], "flaw": bc["flaw"], "score": score, "reason": reason}
        )
        save_json(BAD_CACHE, out)
        print(f"[bad {idx + 1}/{len(data['bad_cases'])}] score={score} <- {bc['flaw']}")
    print(f"\nbad 完成，共 {len(out)} 条")


def percentile(sorted_vals, p):
    if not sorted_vals:
        return 0.0
    k = max(0, min(len(sorted_vals) - 1, int(round(p / 100 * len(sorted_vals) + 0.5)) - 1))
    return sorted_vals[k]


def stage_report():
    """阈值扫描 + 汇总报告（离线）"""
    gate = load_json(GATE_CACHE, {})
    bad = load_json(BAD_CACHE, [])
    cls = load_json(CLS_CACHE, {})

    good_scores = [v["quality_score"] for v in gate.values() if v.get("quality_score") is not None]
    bad_scores = [x["score"] for x in bad]
    n_good, n_bad = len(good_scores), len(bad_scores)

    sweep = []
    for t in range(3, 10):
        fpr = sum(1 for s in good_scores if s < t) / max(n_good, 1)
        tpr = sum(1 for s in bad_scores if s < t) / max(n_bad, 1)
        sweep.append({"threshold": t, "fpr": round(fpr, 4), "tpr": round(tpr, 4)})

    handoffs = sum(1 for v in gate.values() if v["needs_human"])
    fpr6 = handoffs / max(n_good, 1)
    lat = sorted(v["latency_s"] for v in gate.values())
    calls = [v["llm_calls"] for v in gate.values()]
    cls_correct = sum(1 for v in cls.values() if v["expected"] == v["predicted"])

    summary = {
        "classification": {"correct": cls_correct, "total": len(cls),
                           "accuracy": round(cls_correct / max(len(cls), 1), 4)},
        "gate": {"n": n_good, "handoffs": handoffs, "fpr_at_6": round(fpr6, 4),
                 "p50_latency_s": percentile(lat, 50), "p95_latency_s": percentile(lat, 95),
                 "avg_llm_calls": round(sum(calls) / max(len(calls), 1), 2)},
        "bad": {"n": n_bad, "intercepted_at_6": sum(1 for s in bad_scores if s < 6)},
        "threshold_sweep": sweep,
    }
    save_json(os.path.join(RESULTS, "eval_results.json"), summary)

    # 阈值扫描曲线
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei"]
        plt.rcParams["axes.unicode_minus"] = False
        xs = [s["threshold"] for s in sweep]
        fig, ax = plt.subplots(figsize=(7, 4.2))
        ax.plot(xs, [s["tpr"] for s in sweep], marker="o", label="坏例拦截率 TPR")
        ax.plot(xs, [s["fpr"] for s in sweep], marker="s", label="正常回复误拦率 FPR")
        ax.axvline(6, color="gray", ls="--", lw=1, label="当前阈值 = 6")
        ax.set_xlabel("质检阈值")
        ax.set_ylabel("比例")
        ax.set_title("质检阈值扫描：拦截率 - 误拦率权衡")
        ax.legend()
        fig.tight_layout()
        fig.savefig(os.path.join(RESULTS, "threshold_curve.png"), dpi=150)
        print("曲线已保存: evals/results/threshold_curve.png")
    except ImportError:
        print("（未安装 matplotlib，跳过画图）")

    md = [
        "# Aegis-CS 评测报告",
        "",
        f"- 意图分类准确率：**{cls_correct}/{len(cls)} = {summary['classification']['accuracy']:.1%}**（30 题，六桶）",
        f"- 质检误拦率（阈值 6，正常链路 25 题）：**{fpr6:.1%}**",
        f"- 坏例拦截率（阈值 6，构造坏例 {n_bad} 条）："
        f"**{sum(1 for s in bad_scores if s < 6) / max(n_bad, 1):.1%}**",
        f"- 单轮延迟：p50 **{summary['gate']['p50_latency_s']}s** / p95 **{summary['gate']['p95_latency_s']}s**"
        f"（含 {summary['gate']['avg_llm_calls']} 次 LLM 调用/轮）",
        "",
        "## 阈值扫描",
        "",
        "| 阈值 | 坏例拦截率 TPR | 正常回复误拦率 FPR |",
        "|---|---|---|",
    ]
    md += [f"| {s['threshold']} | {s['tpr']:.0%} | {s['fpr']:.0%} |" for s in sweep]
    md += ["", "![threshold](threshold_curve.png)", ""]
    with open(os.path.join(RESULTS, "eval_report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["classify", "gate", "bad", "report", "all"])
    args = parser.parse_args()
    data = load_set()
    if args.stage in ("classify", "all"):
        stage_classify(svc.get_llm(), data)
    if args.stage in ("bad", "all"):
        stage_bad(svc.get_llm(), data)
    if args.stage in ("gate", "all"):
        stage_gate(svc.get_llm(), data)
    if args.stage in ("report", "all"):
        stage_report()
